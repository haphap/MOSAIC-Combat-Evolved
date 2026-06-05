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
from .phase_minus1 import load_jsonl


GOLD_CANDIDATE_CLAIMS_PATH = "registry/gold_sets/tushare_research_reports.candidate_claims.jsonl"
GOLD_CANDIDATE_CLAIMS_SUMMARY_PATH = "registry/gold_sets/tushare_research_reports.candidate_claims.summary.json"
GOLD_CANDIDATES_PATH = "registry/sources/tushare_research_reports.gold_candidates.jsonl"
GOLD_REVIEW_TEMPLATE_PATH = "registry/gold_sets/tushare_research_reports.review_template.jsonl"

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
MANUAL_REVIEW_FIELDS = (
    "manual_claim_text",
    "claim_correct",
    "source_span_supports_claim",
    "direction_correct",
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


def _short_hash(text: str) -> str:
    return "sha256:" + sha256(text.encode("utf-8")).hexdigest()[:16]


def _review_rows_by_source(review_rows: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in review_rows:
        source_id = str(row.get("source_id") or row.get("document_id") or "")
        if source_id:
            grouped.setdefault(source_id, []).append(row)
    return grouped


def _source_sentences(text: str) -> list[tuple[int, int, str, tuple[str, ...]]]:
    prioritized: list[tuple[int, int, str, tuple[str, ...]]] = []
    fallback: list[tuple[int, int, str, tuple[str, ...]]] = []
    for match in SENTENCE_RE.finditer(text):
        sentence = match.group(0).strip()
        keywords = tuple(keyword for keyword in MECHANISM_KEYWORDS if keyword in sentence)
        row = (match.start(), match.end(), sentence, keywords)
        if keywords:
            prioritized.append(row)
        else:
            fallback.append(row)
    return prioritized + fallback


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


def _variable_pair(
    sentence: str,
    *,
    query_key: str,
    industry: str,
    ts_code: str,
    known_variable_ids: set[str],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    text = f"{query_key} {industry} {ts_code} {sentence}"
    cause: list[str] = []
    target: list[str] = []
    flags: list[str] = []

    if any(keyword in text for keyword in ("半导体", "芯片", "存储", "AI", "算力", "国产", "替代")):
        if any(keyword in text for keyword in ("AI", "算力", "存储", "数据中心")):
            cause.append("ai_compute_demand")
            target.append("semiconductor_storage_cycle")
        if any(keyword in text for keyword in ("国产", "替代", "政策", "出口", "限制")):
            cause.append("trade_friction_intensity")
            target.append("semiconductor_policy_substitution_alpha")
    if any(keyword in text for keyword in ("电池", "宁德", "300750", "补能", "充电", "储能")):
        if any(keyword in text for keyword in ("技术", "迭代", "电池", "能量密度", "充电")):
            cause.append("ev_battery_technology_iteration")
        if any(keyword in text for keyword in ("补能", "换电", "充电", "需求")):
            cause.append("ev_charging_ecosystem_demand")
        target.append("battery_profitability_expectation")
    if any(keyword in text for keyword in ("600519", "茅台", "白酒", "渠道", "库存", "消费")):
        cause.append("liquor_demand_recovery")
        target.append("consumer_leader_profitability_expectation")
    if any(keyword in text for keyword in ("银行", "信贷", "利差", "净息差", "流动性", "央行")):
        if any(keyword in text for keyword in ("流动性", "央行", "利率", "资金")):
            cause.append("pboc_net_injection")
            target.append("short_term_liquidity_pressure")
        cause.append("bank_credit_supply")
        target.append("bank_net_interest_margin_pressure")
    if any(keyword in text for keyword in ("估值", "PE", "PB", "分位")):
        cause.append("valuation_percentile")

    cause = [item for item in dict.fromkeys(cause) if item in known_variable_ids]
    target = [item for item in dict.fromkeys(target) if item in known_variable_ids]
    if not cause or not target:
        flags.append("canonical_variable_mapping_needed")
    return tuple(cause), tuple(target), tuple(flags)


def _candidate_claim_for_review_row(
    candidate: Mapping[str, Any],
    review_row: Mapping[str, Any],
    sentence_rows: Sequence[tuple[int, int, str, tuple[str, ...]]],
    row_index: int,
    known_variable_ids: set[str],
) -> GoldCandidateClaim:
    source_id = str(candidate.get("source_id") or review_row.get("source_id") or "")
    source_span_id = str(candidate.get("source_span_id") or review_row.get("source_span_id") or f"{source_id}:abstract")
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
    risk_flags = ["manual_review_required", *variable_flags]
    if not candidate_available:
        risk_flags.append("candidate_unavailable")
    if not keywords:
        risk_flags.append("low_mechanism_keyword_support")
    if str(candidate.get("license_status") or "") != "approved":
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
        extraction_confidence_bin="medium" if candidate_available and not variable_flags else "low",
        review_risk_flags=tuple(dict.fromkeys(risk_flags)),
    )


def build_gold_candidate_claims(root: str | Path = ".") -> tuple[GoldCandidateClaim, ...]:
    root_path = Path(root)
    candidates = load_jsonl(root_path / GOLD_CANDIDATES_PATH)
    review_rows = load_jsonl(root_path / GOLD_REVIEW_TEMPLATE_PATH)
    review_by_source = _review_rows_by_source(review_rows)
    vocabulary = load_claim_variable_vocabulary(root_path)
    known_variable_ids = {variable.variable_id for variable in vocabulary.variables}
    claims: list[GoldCandidateClaim] = []
    for candidate in candidates:
        source_id = str(candidate.get("source_id") or "")
        sentence_rows = _source_sentences(str(candidate.get("abstract") or candidate.get("source_span_text") or ""))
        for idx, review_row in enumerate(review_by_source.get(source_id, ())):
            claims.append(
                _candidate_claim_for_review_row(
                    candidate,
                    review_row,
                    sentence_rows,
                    idx,
                    known_variable_ids,
                )
            )
    return tuple(claims)


def merge_candidate_claims_into_review_template(
    root: str | Path = ".",
    *,
    candidate_claims: Sequence[GoldCandidateClaim] | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    review_path = root_path / GOLD_REVIEW_TEMPLATE_PATH
    rows = load_jsonl(review_path)
    claims = candidate_claims or build_gold_candidate_claims(root_path)
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
                    "proposed_extraction_confidence_bin": claim.extraction_confidence_bin,
                    "proposed_review_risk_flags": list(claim.review_risk_flags),
                    "proposed_verifier_status": claim.verifier_status,
                }
            )
        merged.append(out)
    _write_jsonl(review_path, merged)
    manual_after = {
        str(row.get("claim_id") or ""): {field: row.get(field) for field in MANUAL_REVIEW_FIELDS}
        for row in merged
    }
    return {
        "path": str(review_path),
        "rows": len(merged),
        "rows_with_candidate_fields": sum("proposed_claim_text" in row for row in merged),
        "manual_fields_preserved": manual_before == manual_after,
    }


def build_gold_candidate_claim_summary(
    root: str | Path = ".",
    *,
    candidate_claims: Sequence[GoldCandidateClaim] | None = None,
    review_merge_result: Mapping[str, Any] | None = None,
) -> GoldCandidateClaimSummary:
    claims = tuple(candidate_claims or build_gold_candidate_claims(root))
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
    )


def write_gold_candidate_claims(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    claims = build_gold_candidate_claims(root_path)
    claims_result = _write_jsonl(root_path / GOLD_CANDIDATE_CLAIMS_PATH, [asdict(claim) for claim in claims])
    merge_result = merge_candidate_claims_into_review_template(root_path, candidate_claims=claims)
    summary = build_gold_candidate_claim_summary(
        root_path,
        candidate_claims=claims,
        review_merge_result=merge_result,
    )
    summary_result = _write_json(root_path / GOLD_CANDIDATE_CLAIMS_SUMMARY_PATH, asdict(summary))
    return {
        "candidate_claims": str(claims_result["path"]),
        "summary": str(summary_result["path"]),
        "review_template": str(merge_result["path"]),
    }
