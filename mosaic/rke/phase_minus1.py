"""Phase -1 feasibility helpers for RKE.

Phase -1 is not production validation. It audits source corpora and prepares
gold-set sampling so the team can decide whether schema freeze is justified.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .p0 import ClaimExtractionGoldSet


REQUIRED_SOURCE_ROW_FIELDS = {
    "source_id",
    "source_span_id",
    "source_type",
    "publish_date",
    "discovered_at",
    "title",
    "abstract",
    "source_hash",
    "point_in_time_available",
    "license_status",
}

GOLD_SET_DOMAIN_KEYWORD_SPECS: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "central_bank": {
        "strong": (
            "央行",
            "中国人民银行",
            "公开市场",
            "逆回购",
            "买断式逆回购",
            "货币政策",
            "降准",
            "降息",
            "LPR",
            "MLF",
            "SLF",
            "OMO",
        ),
        "weak": (
            "流动性",
            "信贷",
            "利率",
            "银行间",
            "资金面",
            "国债收益率",
        ),
    },
    "dollar": {
        "strong": (
            "美元",
            "DXY",
            "美元指数",
            "USDCNY",
            "USDCNH",
            "人民币汇率",
            "中美利差",
            "美联储",
            "Fed",
            "美债",
        ),
        "weak": (
            "汇率",
            "人民币",
            "离岸",
            "外资",
        ),
    },
    "volatility": {
        "strong": (
            "VIX",
            "iVX",
            "隐含波动率",
            "realized volatility",
            "风险偏好",
            "风险溢价",
            "避险",
            "回撤",
        ),
        "weak": (
            "波动",
            "震荡",
            "风险",
            "下跌",
            "调整",
        ),
    },
    "semiconductor": {
        "strong": (
            "半导体",
            "芯片",
            "集成电路",
            "晶圆",
            "存储芯片",
            "HBM",
            "DRAM",
            "NAND",
            "封测",
            "光刻",
            "EDA",
        ),
        "weak": (
            "存储",
            "算力",
            "国产替代",
            "AI算力",
            "数据中心",
        ),
    },
}
GOLD_SET_DOMAIN_KEYWORDS: Mapping[str, tuple[str, ...]] = {
    domain: tuple(keyword for keywords in spec.values() for keyword in keywords)
    for domain, spec in GOLD_SET_DOMAIN_KEYWORD_SPECS.items()
}
REQUIRED_GOLD_SET_DOMAINS = tuple(GOLD_SET_DOMAIN_KEYWORD_SPECS)
GOLD_SET_DOMAIN_KEYWORD_WEIGHTS = {"strong": 3, "weak": 1}


@dataclass(frozen=True)
class CorpusAudit:
    row_count: int
    rows_with_abstract: int
    report_type_counts: Mapping[str, int]
    query_key_counts: Mapping[str, int]
    publish_date_min: str | None
    publish_date_max: str | None
    missing_required_fields: Mapping[str, tuple[str, ...]]
    duplicate_source_hashes: tuple[str, ...]
    production_blockers: tuple[str, ...]

    @property
    def ready_for_gold_set_sampling(self) -> bool:
        return (
            self.row_count > 0
            and self.rows_with_abstract == self.row_count
            and not self.missing_required_fields
            and not self.duplicate_source_hashes
        )


@dataclass(frozen=True)
class GoldSetReviewRecord:
    source_id: str
    source_span_id: str
    claim_id: str
    document_id: str
    claim_correct: bool
    source_span_supports_claim: bool
    direction_correct: bool
    variable_mapping_correct: bool
    unsupported_field_false_grounded: bool


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def audit_research_report_corpus(rows: Sequence[Mapping[str, Any]]) -> CorpusAudit:
    report_type_counts = Counter(str(row.get("report_type") or "") for row in rows)
    query_key_counts = Counter(str(row.get("query_key") or "") for row in rows)
    publish_dates = sorted(str(row.get("publish_date") or "") for row in rows if row.get("publish_date"))
    hash_counts = Counter(str(row.get("source_hash") or "") for row in rows)
    duplicate_hashes = tuple(sorted(hash_value for hash_value, count in hash_counts.items() if hash_value and count > 1))

    missing: dict[str, tuple[str, ...]] = {}
    blockers: list[str] = []
    for row in rows:
        source_id = str(row.get("source_id") or f"row-{len(missing)}")
        row_missing = tuple(sorted(field for field in REQUIRED_SOURCE_ROW_FIELDS if row.get(field) in (None, "")))
        if row_missing:
            missing[source_id] = row_missing
        if row.get("license_status") != "approved":
            blockers.append(f"{source_id}: license_status={row.get('license_status')} blocks production")
        if row.get("point_in_time_available") is not True:
            blockers.append(f"{source_id}: point_in_time_available is not true")

    return CorpusAudit(
        row_count=len(rows),
        rows_with_abstract=sum(bool(str(row.get("abstract") or "").strip()) for row in rows),
        report_type_counts=dict(report_type_counts),
        query_key_counts=dict(query_key_counts),
        publish_date_min=publish_dates[0] if publish_dates else None,
        publish_date_max=publish_dates[-1] if publish_dates else None,
        missing_required_fields=missing,
        duplicate_source_hashes=duplicate_hashes,
        production_blockers=tuple(blockers),
    )


def select_gold_set_candidates(
    rows: Sequence[Mapping[str, Any]],
    *,
    max_documents: int = 50,
) -> list[dict[str, Any]]:
    """Select a deterministic, domain-stratified manual-review sample.

    Phase -1 needs a gold set that covers the planned macro/sector domains, not
    just the first lexicographic stock-code buckets. Rows may match multiple
    domains; the selected row records both the assigned domain and all matched
    domains for reviewer audit.
    """
    if max_documents <= 0:
        return []
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    assigned_counts: Counter[str] = Counter()
    per_domain_quota = max(1, max_documents // (len(REQUIRED_GOLD_SET_DOMAINS) + 1))

    def add_row(row: Mapping[str, Any], assigned_domain: str) -> bool:
        source_id = str(row.get("source_id") or "")
        if not source_id or source_id in seen or len(selected) >= max_documents:
            return False
        out = dict(row)
        domains = _gold_set_domains(row)
        evidence = _gold_set_domain_evidence(row)
        out["gold_set_domain"] = assigned_domain
        out["gold_set_domains"] = domains
        out["gold_set_domain_scores"] = {
            domain: int(details["score"]) for domain, details in evidence.items()
        }
        out["gold_set_domain_matches"] = {
            domain: list(details["keywords"]) for domain, details in evidence.items()
        }
        selected.append(out)
        seen.add(source_id)
        assigned_counts[assigned_domain] += 1
        return True

    domain_buckets: dict[str, list[Mapping[str, Any]]] = {
        domain: [] for domain in REQUIRED_GOLD_SET_DOMAINS
    }
    global_buckets: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    ordered = _ordered_gold_set_source_rows(rows)
    for row in ordered:
        for domain in _gold_set_domains(row):
            if domain in domain_buckets:
                domain_buckets[domain].append(row)
        global_buckets.setdefault(
            (str(row.get("query_key") or ""), str(row.get("report_type") or "")),
            [],
        ).append(row)

    for domain in REQUIRED_GOLD_SET_DOMAINS:
        domain_selected = 0
        while domain_selected < per_domain_quota and len(selected) < max_documents:
            row = _pop_next_domain_row(domain_buckets[domain], seen)
            if row is None:
                break
            if add_row(row, domain):
                domain_selected += 1

    while len(selected) < max_documents:
        progressed = False
        for bucket in sorted(global_buckets):
            candidates = global_buckets[bucket]
            while candidates:
                row = candidates.pop(0)
                domains = tuple(domain for domain in _gold_set_domains(row) if domain in REQUIRED_GOLD_SET_DOMAINS)
                assigned_domain = next(
                    (domain for domain in domains if assigned_counts[domain] < per_domain_quota),
                    "other",
                )
                if add_row(row, assigned_domain):
                    progressed = True
                    break
            if len(selected) >= max_documents:
                break
        if not progressed:
            break
    return selected


def _gold_set_text(row: Mapping[str, Any]) -> str:
    return " ".join(
        str(row.get(field) or "")
        for field in ("query_key", "industry", "title", "abstract", "report_type", "ts_code")
    )


def _gold_set_domains(row: Mapping[str, Any]) -> tuple[str, ...]:
    evidence = _gold_set_domain_evidence(row)
    domains = tuple(
        sorted(
            evidence,
            key=lambda domain: (-int(evidence[domain]["score"]), domain),
        )
    )
    return domains or ("other",)


def _gold_set_domain_evidence(row: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    text = _gold_set_text(row)
    lowered = text.lower()
    evidence: dict[str, dict[str, Any]] = {}
    for domain, spec in GOLD_SET_DOMAIN_KEYWORD_SPECS.items():
        score = 0
        has_strong = False
        keywords: list[str] = []
        for strength, candidates in spec.items():
            weight = GOLD_SET_DOMAIN_KEYWORD_WEIGHTS[strength]
            for keyword in candidates:
                if keyword.lower() in lowered:
                    score += weight
                    has_strong = has_strong or strength == "strong"
                    keywords.append(keyword)
        if has_strong or score >= 2:
            evidence[domain] = {
                "score": score,
                "keywords": tuple(dict.fromkeys(keywords)),
            }
    return evidence


def _ordered_gold_set_source_rows(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    report_type_rank = {"行业研报": 0, "个股研报": 1}
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("publish_date") or ""),
            -report_type_rank.get(str(row.get("report_type") or ""), 9),
            str(row.get("query_key") or ""),
            str(row.get("source_id") or ""),
        ),
        reverse=True,
    )


def _pop_next_domain_row(
    candidates: list[Mapping[str, Any]],
    seen: set[str],
) -> Mapping[str, Any] | None:
    for index, row in enumerate(candidates):
        source_id = str(row.get("source_id") or "")
        if source_id and source_id not in seen:
            return candidates.pop(index)
    return None


def write_gold_set_candidates(
    candidates: Iterable[Mapping[str, Any]],
    output_path: str | Path,
) -> dict[str, Any]:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(candidates)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {"path": str(path), "rows": len(rows)}


def build_gold_set_review_template(
    candidates: Sequence[Mapping[str, Any]],
    *,
    claims_per_document: int = 10,
    span_preview_chars: int = 600,
) -> list[dict[str, Any]]:
    """Create blank manual-review rows from sampled source documents."""
    if claims_per_document <= 0:
        raise ValueError("claims_per_document must be positive")
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        source_id = str(candidate.get("source_id") or "")
        span_id = str(candidate.get("source_span_id") or f"{source_id}:abstract")
        text = str(candidate.get("abstract") or candidate.get("source_span_text") or "")
        for idx in range(1, claims_per_document + 1):
            rows.append(
                {
                    "source_id": source_id,
                    "source_span_id": span_id,
                    "claim_id": f"GOLD-{source_id}-{idx:03d}",
                    "document_id": source_id,
                    "gold_set_domain": str(candidate.get("gold_set_domain") or "other"),
                    "gold_set_domains": tuple(candidate.get("gold_set_domains") or ()),
                    "gold_set_domain_matches": dict(candidate.get("gold_set_domain_matches") or {}),
                    "gold_set_domain_scores": dict(candidate.get("gold_set_domain_scores") or {}),
                    "span_preview": text[:span_preview_chars],
                    "manual_claim_text": "",
                    "claim_correct": None,
                    "source_span_supports_claim": None,
                    "direction_correct": None,
                    "variable_mapping_correct": None,
                    "unsupported_field_false_grounded": None,
                    "reviewer": "",
                    "review_notes": "",
                }
            )
    return rows


def write_gold_set_review_template(
    candidates: Sequence[Mapping[str, Any]],
    output_path: str | Path,
    *,
    claims_per_document: int = 10,
) -> dict[str, Any]:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = build_gold_set_review_template(candidates, claims_per_document=claims_per_document)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {"path": str(path), "rows": len(rows)}


def evaluate_gold_set_reviews(
    records: Sequence[GoldSetReviewRecord | Mapping[str, Any]],
    *,
    gold_set_id: str,
) -> ClaimExtractionGoldSet:
    normalized: list[dict[str, Any]] = [
        asdict(record) if isinstance(record, GoldSetReviewRecord) else dict(record)
        for record in records
    ]
    n = len(normalized)
    if n == 0:
        return ClaimExtractionGoldSet(
            gold_set_id=gold_set_id,
            sample_size_documents=0,
            sample_size_claims=0,
            claim_precision=0.0,
            source_span_support_precision=0.0,
            direction_accuracy=0.0,
            variable_mapping_accuracy=0.0,
            unsupported_field_false_grounding_rate=1.0,
        )
    documents = {str(record.get("document_id") or record.get("source_id") or "") for record in normalized}

    def rate(field: str) -> float:
        return round(sum(record.get(field) is True for record in normalized) / n, 6)

    return ClaimExtractionGoldSet(
        gold_set_id=gold_set_id,
        sample_size_documents=len(documents - {""}),
        sample_size_claims=n,
        claim_precision=rate("claim_correct"),
        source_span_support_precision=rate("source_span_supports_claim"),
        direction_accuracy=rate("direction_correct"),
        variable_mapping_accuracy=rate("variable_mapping_correct"),
        unsupported_field_false_grounding_rate=round(
            sum(record.get("unsupported_field_false_grounded") is True for record in normalized) / n,
            6,
        ),
    )
