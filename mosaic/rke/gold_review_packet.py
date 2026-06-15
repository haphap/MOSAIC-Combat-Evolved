"""Gold-set manual review packet for RKE Phase -1.

The packet is deliberately a review aid, not an automated labeler. It points
human reviewers to source-bound span ranges, pending claim rows, and likely
review risks without filling the manual gate fields.
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


GOLD_REVIEW_PACKET_JSON_PATH = "registry/gold_sets/tushare_research_reports.review_packet.json"
GOLD_REVIEW_PACKET_MD_PATH = "registry/gold_sets/tushare_research_reports.review_packet.md"
GOLD_CANDIDATE_CLAIMS_SUMMARY_PATH = "registry/gold_sets/tushare_research_reports.candidate_claims.summary.json"
GOLD_CANDIDATES_PATH = "registry/sources/tushare_research_reports.gold_candidates.jsonl"
GOLD_REVIEW_TEMPLATE_PATH = "registry/gold_sets/tushare_research_reports.review_template.jsonl"
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
)
SENTENCE_RE = re.compile(r"[^。！？!?；;\n]{12,260}[。！？!?；;]?")


@dataclass(frozen=True)
class CandidateSpanRef:
    span_ref_id: str
    source_span_id: str
    start_char: int
    end_char: int
    reason_keywords: Sequence[str]
    suggested_claim_type: str
    contains_numeric_evidence: bool
    text_hash: str
    text_preview: str


@dataclass(frozen=True)
class GoldReviewDocumentPacket:
    source_id: str
    source_span_id: str
    gold_set_domain: str
    gold_set_domains: Sequence[str]
    gold_set_domain_matches: Mapping[str, Sequence[str]]
    gold_set_domain_scores: Mapping[str, int]
    title: str
    publish_date: str
    report_type: str
    query_key: str
    institution: str
    review_claim_ids: Sequence[str]
    pending_claim_rows: int
    candidate_span_refs: Sequence[CandidateSpanRef]
    canonical_variable_hints: Sequence[str]
    unmapped_source_terms: Sequence[str]
    risk_flags: Sequence[str]


@dataclass(frozen=True)
class GoldReviewPacket:
    packet_id: str
    status: str
    review_gate: Mapping[str, Any]
    review_field_contract: Sequence[str]
    candidate_path: str
    review_path: str
    document_count: int
    review_row_count: int
    pending_review_rows: int
    candidate_claim_count: int
    candidate_claim_available_count: int
    review_rows_with_candidate_fields: int
    candidate_span_ref_count: int
    domain_counts: Mapping[str, int]
    query_key_counts: Mapping[str, int]
    report_type_counts: Mapping[str, int]
    risk_flag_counts: Mapping[str, int]
    blockers: Sequence[str]
    documents: Sequence[GoldReviewDocumentPacket]

    @property
    def manual_review_required(self) -> bool:
        return bool(self.blockers) or self.pending_review_rows > 0 or self.status != "manual_review_passed"


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


def _optional_json(path: Path, label: str) -> tuple[dict[str, Any], tuple[str, ...]]:
    if not path.exists():
        return {}, ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, (f"{label} must contain valid JSON: {exc.msg}",)
    if not isinstance(payload, Mapping):
        return {}, (f"{label} must be object",)
    return dict(payload), ()


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


def _short_hash(text: str) -> str:
    return "sha256:" + sha256(text.encode("utf-8")).hexdigest()[:16]


def _span_preview(text: str, *, max_chars: int = 180) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."


def _candidate_span_refs(text: str, source_span_id: str, *, limit: int = 5) -> tuple[CandidateSpanRef, ...]:
    refs: list[CandidateSpanRef] = []
    for idx, match in enumerate(SENTENCE_RE.finditer(text), 1):
        sentence = match.group(0).strip()
        keywords = tuple(keyword for keyword in MECHANISM_KEYWORDS if keyword in sentence)
        if not keywords:
            continue
        claim_type = "causal_mechanism"
        if any(keyword in sentence for keyword in ("风险", "承压", "下降")):
            claim_type = "failure_or_constraint"
        elif any(keyword in sentence for keyword in ("估值", "价格", "盈利")):
            claim_type = "valuation_or_fundamental_link"
        refs.append(
            CandidateSpanRef(
                span_ref_id=f"{source_span_id}:sent-{idx:02d}",
                source_span_id=source_span_id,
                start_char=match.start(),
                end_char=match.end(),
                reason_keywords=keywords,
                suggested_claim_type=claim_type,
                contains_numeric_evidence=bool(re.search(r"\d", sentence)),
                text_hash=_short_hash(sentence),
                text_preview=_span_preview(sentence),
            )
        )
        if len(refs) >= limit:
            break
    return tuple(refs)


def _canonical_variable_hints(text: str, query_key: str, report_type: str) -> tuple[str, ...]:
    hints: set[str] = set()
    text_upper = text.upper()
    semiconductor_context_terms = (
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
    storage_cycle_terms = (
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
    semiconductor_policy_terms = (
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
    ai_compute_terms = ("AI", "AIGC", "算力", "人工智能", "大模型", "数据中心", "云", "Token", "推理")
    has_semiconductor_context = "半导体" in query_key or any(
        keyword in text for keyword in semiconductor_context_terms
    )
    has_storage_cycle_context = any(keyword in text_upper for keyword in storage_cycle_terms)
    if any(keyword in text for keyword in ai_compute_terms) or has_storage_cycle_context:
        hints.add("ai_compute_demand")
    if has_semiconductor_context:
        if any(keyword in text for keyword in semiconductor_policy_terms):
            hints.update(("trade_friction_intensity", "semiconductor_policy_substitution_alpha"))
        if has_storage_cycle_context:
            hints.add("semiconductor_storage_cycle")
    if "银行" in query_key or "流动性" in text or "央行" in text:
        hints.update(("pboc_net_injection", "short_term_liquidity_pressure"))
    if any(keyword in text for keyword in ("估值", "PE", "PB", "分位")):
        hints.add("valuation_percentile")
    if "行业研报" in report_type and any(keyword in text for keyword in ("政策", "催化")):
        hints.add("forward_alpha_after_policy_catalyst")
    return tuple(sorted(hints))


def _source_terms(text: str) -> tuple[str, ...]:
    return tuple(keyword for keyword in MECHANISM_KEYWORDS if keyword in text)


def _review_rows_by_source(review_rows: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in review_rows:
        source_id = str(row.get("source_id") or row.get("document_id") or "")
        if source_id:
            grouped.setdefault(source_id, []).append(row)
    return grouped


def _row_pending(row: Mapping[str, Any]) -> bool:
    required_fields = (
        "claim_correct",
        "source_span_supports_claim",
        "direction_correct",
        "target_correct",
        "horizon_correct",
        "variable_mapping_correct",
        "unsupported_field_false_grounded",
    )
    return any(row.get(field) is None for field in required_fields)


def _document_packet(
    candidate: Mapping[str, Any],
    review_rows: Sequence[Mapping[str, Any]],
    known_variable_ids: set[str],
    approved_license_source_ids: set[str],
) -> GoldReviewDocumentPacket:
    source_id = str(candidate.get("source_id") or "")
    source_span_id = str(candidate.get("source_span_id") or f"{source_id}:abstract")
    text = str(candidate.get("abstract") or candidate.get("source_span_text") or "")
    query_key = str(candidate.get("query_key") or "")
    report_type = str(candidate.get("report_type") or "")
    hints = tuple(variable for variable in _canonical_variable_hints(text, query_key, report_type) if variable in known_variable_ids)
    source_terms = _source_terms(text)
    risk_flags: list[str] = ["manual_review_required"]
    if source_id not in approved_license_source_ids and str(candidate.get("license_status") or "") != "approved":
        risk_flags.append("license_pending")
    if len(text) > 600:
        risk_flags.append("span_preview_truncated")
    if not hints:
        risk_flags.append("canonical_variable_mapping_needed")
    if not _candidate_span_refs(text, source_span_id):
        risk_flags.append("no_mechanism_sentence_detected")
    if not str(candidate.get("url") or "").strip():
        risk_flags.append("source_url_missing")

    return GoldReviewDocumentPacket(
        source_id=source_id,
        source_span_id=source_span_id,
        gold_set_domain=str(candidate.get("gold_set_domain") or "other"),
        gold_set_domains=tuple(candidate.get("gold_set_domains") or ("other",)),
        gold_set_domain_matches=dict(candidate.get("gold_set_domain_matches") or {}),
        gold_set_domain_scores={
            str(domain): int(score)
            for domain, score in dict(candidate.get("gold_set_domain_scores") or {}).items()
        },
        title=str(candidate.get("title") or ""),
        publish_date=str(candidate.get("publish_date") or ""),
        report_type=report_type,
        query_key=query_key,
        institution=str(candidate.get("institution") or ""),
        review_claim_ids=tuple(str(row.get("claim_id") or "") for row in review_rows),
        pending_claim_rows=sum(_row_pending(row) for row in review_rows),
        candidate_span_refs=_candidate_span_refs(text, source_span_id),
        canonical_variable_hints=hints,
        unmapped_source_terms=tuple(term for term in source_terms if not hints),
        risk_flags=tuple(dict.fromkeys(risk_flags)),
    )


def build_gold_review_packet(root: str | Path = ".") -> GoldReviewPacket:
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
    candidate_claim_summary, summary_blockers = _optional_json(
        root_path / GOLD_CANDIDATE_CLAIMS_SUMMARY_PATH,
        "gold candidate summary",
    )
    approved_license_source_ids, license_review_blockers = _approved_license_source_ids(root_path)
    vocabulary_blockers: tuple[str, ...] = ()
    try:
        vocabulary = load_claim_variable_vocabulary(root_path)
        known_variable_ids = {variable.variable_id for variable in vocabulary.variables}
    except ValueError as exc:
        known_variable_ids = set()
        vocabulary_blockers = (str(exc),)
    documents = tuple(
        _document_packet(
            candidate,
            review_by_source.get(str(candidate.get("source_id") or ""), ()),
            known_variable_ids,
            approved_license_source_ids,
        )
        for candidate in candidates
    )
    risk_counts = Counter(flag for document in documents for flag in document.risk_flags)
    domain_counts = Counter(document.gold_set_domain for document in documents)
    query_key_counts = Counter(document.query_key for document in documents)
    report_type_counts = Counter(document.report_type for document in documents)
    blockers: list[str] = [
        *candidate_parse_blockers,
        *review_parse_blockers,
        *summary_blockers,
        *license_review_blockers,
        *vocabulary_blockers,
    ]
    if invalid_candidate_rows:
        blockers.append(
            "gold candidate row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in invalid_candidate_rows)
        )
    if invalid_review_rows:
        blockers.append(
            "gold-set review row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in invalid_review_rows)
        )
    pending_review_rows = sum(_row_pending(row) for row in review_rows)
    status = (
        "manual_review_blocked"
        if blockers
        else "manual_review_pending"
        if pending_review_rows
        else "manual_review_passed"
    )
    return GoldReviewPacket(
        packet_id="RKE-GOLD-REVIEW-PACKET-20260606",
        status=status,
        review_gate={
            "gold_set_id": "GOLD-CLAIM-2026Q2",
            "claim_precision_min": 0.85,
            "source_span_support_precision_min": 0.90,
            "direction_accuracy_min": 0.85,
            "target_accuracy_min": 0.85,
            "horizon_accuracy_min": 0.85,
            "variable_mapping_accuracy_min": 0.80,
            "unsupported_field_false_grounding_max": 0.05,
            "gate": "schema_freeze_blocked_until_pass",
        },
        review_field_contract=(
            "manual_claim_text",
            "claim_correct",
            "source_span_supports_claim",
            "direction_correct",
            "target_correct",
            "horizon_correct",
            "variable_mapping_correct",
            "unsupported_field_false_grounded",
            "reviewer",
            "review_date",
            "review_notes",
        ),
        candidate_path=GOLD_CANDIDATES_PATH,
        review_path=GOLD_REVIEW_TEMPLATE_PATH,
        document_count=len(documents),
        review_row_count=len(raw_review_rows) + len(review_parse_blockers),
        pending_review_rows=pending_review_rows,
        candidate_claim_count=int(candidate_claim_summary.get("candidate_claim_count") or 0),
        candidate_claim_available_count=int(
            candidate_claim_summary.get("candidate_available_count") or 0
        ),
        review_rows_with_candidate_fields=int(
            candidate_claim_summary.get("review_rows_with_candidate_fields") or 0
        ),
        candidate_span_ref_count=sum(len(document.candidate_span_refs) for document in documents),
        domain_counts=dict(domain_counts),
        query_key_counts=dict(query_key_counts),
        report_type_counts=dict(report_type_counts),
        risk_flag_counts=dict(risk_counts),
        blockers=tuple(blockers),
        documents=documents,
    )


def render_gold_review_packet_markdown(packet: GoldReviewPacket) -> str:
    lines = [
        "# RKE Gold Review Packet",
        "",
        f"- Status: {packet.status}",
        f"- Documents: {packet.document_count}",
        f"- Review rows: {packet.review_row_count}",
        f"- Pending review rows: {packet.pending_review_rows}",
        f"- Candidate claims: {packet.candidate_claim_count}",
        f"- Candidate claims with source text: {packet.candidate_claim_available_count}",
        f"- Review rows with candidate fields: {packet.review_rows_with_candidate_fields}",
        f"- Candidate span refs: {packet.candidate_span_ref_count}",
        f"- Manual review required: {str(packet.manual_review_required).lower()}",
        "",
        "## Gate",
        "",
    ]
    for key, value in packet.review_gate.items():
        lines.append(f"- {key}: {value}")
    if packet.blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- {blocker}" for blocker in packet.blockers)
    lines.extend(["", "## Coverage", ""])
    lines.append(f"- Query keys: {json.dumps(dict(packet.query_key_counts), ensure_ascii=False, sort_keys=True)}")
    lines.append(f"- Domains: {json.dumps(dict(packet.domain_counts), ensure_ascii=False, sort_keys=True)}")
    lines.append(f"- Report types: {json.dumps(dict(packet.report_type_counts), ensure_ascii=False, sort_keys=True)}")
    lines.append(f"- Risk flags: {json.dumps(dict(packet.risk_flag_counts), ensure_ascii=False, sort_keys=True)}")
    lines.extend(["", "## Review Queue", ""])
    for document in packet.documents:
        span_refs = "; ".join(
            (
                f"{span.start_char}-{span.end_char}:{'/'.join(span.reason_keywords[:3])} "
                f"preview={json.dumps(span.text_preview, ensure_ascii=False)}"
            )
            for span in document.candidate_span_refs[:3]
        )
        hints = ", ".join(document.canonical_variable_hints) or "needs reviewer mapping"
        flags = ", ".join(document.risk_flags)
        domain_hits = "/".join(document.gold_set_domain_matches.get(document.gold_set_domain, ())[:4]) or "none"
        lines.append(
            f"- {document.source_id} | {document.publish_date} | {document.gold_set_domain} | {document.query_key} | "
            f"{document.report_type} | pending={document.pending_claim_rows} | vars={hints} | "
            f"domain_hits={domain_hits} | spans={span_refs or 'none'} | flags={flags}"
        )
    return "\n".join(lines)


def write_gold_review_packet(root: str | Path = ".") -> dict[str, str]:
    root_path = Path(root)
    packet = build_gold_review_packet(root_path)
    json_result = _write_json(
        root_path / GOLD_REVIEW_PACKET_JSON_PATH,
        {**asdict(packet), "manual_review_required": packet.manual_review_required},
    )
    md_path = root_path / GOLD_REVIEW_PACKET_MD_PATH
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_gold_review_packet_markdown(packet) + "\n", encoding="utf-8")
    return {"json": str(json_result["path"]), "markdown": str(md_path)}
