"""Claim grounding checker for RKE source-grounded claim contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase_minus1 import load_jsonl_with_errors


CLAIM_GROUNDING_REPORT_PATH = (
    "registry/claim_checks/claim_grounding_validation_report.json"
)
CLAIM_PATHS = (
    "registry/claims/central_bank_claims.jsonl",
    "registry/claims/semiconductor_claims.jsonl",
)
HYPOTHESIS_PATHS = (
    "registry/hypotheses/central_bank_hypotheses.jsonl",
    "registry/hypotheses/semiconductor_hypotheses.jsonl",
)
SOURCE_PATHS = (
    "registry/sources/central_bank_sources.jsonl",
    "registry/sources/semiconductor_demo_sources.jsonl",
    "registry/sources/tushare_research_reports.jsonl",
)
RULE_PACK_PATHS = (
    "registry/rule_packs/macro.central_bank.liquidity.v1.json",
    "registry/rule_packs/sector.semiconductor.policy_substitution.v1.json",
)
ALLOWED_DIRECTIONS = {"positive", "negative", "neutral", "ambiguous"}
ALLOWED_VERIFIER_STATUSES = {"pending", "passed", "failed", "requires_review"}


@dataclass(frozen=True)
class ClaimGroundingValidationRecord:
    check_id: str
    artifact_paths: Sequence[str]
    accepted: bool
    failures: Sequence[str]
    details: Mapping[str, Any]


@dataclass(frozen=True)
class ClaimGroundingValidationReport:
    report_id: str
    records: Sequence[ClaimGroundingValidationRecord]

    @property
    def accepted(self) -> bool:
        return all(record.accepted for record in self.records)

    @property
    def failure_count(self) -> int:
        return sum(len(record.failures) for record in self.records)


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
    path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return {"path": str(path), "rows": 1}


def _record(
    check_id: str,
    artifact_paths: Sequence[str],
    failures: Sequence[str],
    details: Mapping[str, Any] | None = None,
) -> ClaimGroundingValidationRecord:
    return ClaimGroundingValidationRecord(
        check_id=check_id,
        artifact_paths=tuple(artifact_paths),
        accepted=not failures,
        failures=tuple(failures),
        details=dict(details or {}),
    )


def _load_jsonl_rows(
    root_path: Path,
    paths: Sequence[str],
    *,
    label: str,
) -> tuple[list[Mapping[str, Any]], list[str]]:
    rows: list[Mapping[str, Any]] = []
    failures: list[str] = []
    for relative in paths:
        path = root_path / relative
        if not path.exists():
            failures.append(f"{relative}: missing")
            continue
        loaded, parse_failures = load_jsonl_with_errors(path, label=relative)
        failures.extend(parse_failures)
        for index, row in enumerate(loaded, 1):
            if isinstance(row, Mapping):
                rows.append(row)
            else:
                failures.append(f"{relative} row {index} must be object")
    if not rows:
        failures.append(f"{label}: required non-empty")
    return rows, failures


def _read_json_object(
    path: Path, relative: str
) -> tuple[Mapping[str, Any] | None, str]:
    if not path.exists():
        return None, f"{relative}: missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"{relative} must contain valid JSON: {exc.msg}"
    if not isinstance(payload, Mapping):
        return None, f"{relative} must be object"
    return payload, ""


def _source_index(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[set[str], dict[str, set[str]]]:
    source_ids: set[str] = set()
    span_ids: dict[str, set[str]] = {}
    for row in rows:
        source_id = str(row.get("source_id") or "").strip()
        if not source_id:
            continue
        source_ids.add(source_id)
        spans = span_ids.setdefault(source_id, set())
        span = str(row.get("source_span_id") or "").strip()
        if span:
            spans.add(span)
        raw_spans = row.get("source_span_ids")
        if isinstance(raw_spans, Sequence) and not isinstance(raw_spans, (str, bytes)):
            spans.update(str(item).strip() for item in raw_spans if str(item).strip())
    return source_ids, span_ids


def _claim_grounding_record(
    root_path: Path,
) -> tuple[ClaimGroundingValidationRecord, dict[str, Mapping[str, Any]], set[str]]:
    claims, claim_failures = _load_jsonl_rows(root_path, CLAIM_PATHS, label="claims")
    sources, source_failures = _load_jsonl_rows(
        root_path, SOURCE_PATHS, label="sources"
    )
    source_ids, source_span_ids = _source_index(sources)
    failures = list(claim_failures) + list(source_failures)
    claims_by_id: dict[str, Mapping[str, Any]] = {}
    seen_claim_ids: set[str] = set()
    span_checked_count = 0
    verifier_passed_count = 0
    for claim in claims:
        claim_id = str(claim.get("claim_id") or "").strip()
        source_id = str(claim.get("source_id") or "").strip()
        source_span_id = str(claim.get("source_span_id") or "").strip()
        if not claim_id:
            failures.append("claim_id: required")
        elif claim_id in seen_claim_ids:
            failures.append(f"{claim_id}: duplicate claim_id")
        else:
            seen_claim_ids.add(claim_id)
            claims_by_id[claim_id] = claim
        if not source_id:
            failures.append(f"{claim_id or '<unknown>'}: source_id required")
        elif source_id not in source_ids:
            failures.append(f"{claim_id}: source_id not found: {source_id}")
        if not source_span_id:
            failures.append(f"{claim_id}: source_span_id required")
        elif source_id in source_span_ids and source_span_ids[source_id]:
            span_checked_count += 1
            if source_span_id not in source_span_ids[source_id]:
                failures.append(
                    f"{claim_id}: source_span_id not registered for {source_id}"
                )
        if not str(claim.get("claim_text") or "").strip():
            failures.append(f"{claim_id}: claim_text required")
        if claim.get("unsupported_fields"):
            failures.append(
                f"{claim_id}: unsupported_fields must be moved to hypothesis layer"
            )
        direction = str(claim.get("direction") or "")
        if direction not in ALLOWED_DIRECTIONS:
            failures.append(f"{claim_id}: direction invalid")
        elif direction == "ambiguous":
            failures.append(f"{claim_id}: ambiguous direction cannot compile")
        verifier_status = str(claim.get("verifier_status") or "")
        if verifier_status not in ALLOWED_VERIFIER_STATUSES:
            failures.append(f"{claim_id}: verifier_status invalid")
        elif verifier_status == "passed":
            verifier_passed_count += 1
        else:
            failures.append(
                f"{claim_id}: verifier_status must be passed before rule compilation"
            )
    return (
        _record(
            "CLAIM-GROUNDING-CONTRACT",
            (*CLAIM_PATHS, *SOURCE_PATHS),
            failures,
            {
                "claim_count": len(claims),
                "source_count": len(source_ids),
                "span_checked_count": span_checked_count,
                "verifier_passed_count": verifier_passed_count,
            },
        ),
        claims_by_id,
        set(claims_by_id),
    )


def _hypothesis_separation_record(
    root_path: Path,
    known_claim_ids: set[str],
) -> tuple[ClaimGroundingValidationRecord, set[str]]:
    hypotheses, failures = _load_jsonl_rows(
        root_path,
        HYPOTHESIS_PATHS,
        label="hypotheses",
    )
    known_hypotheses: set[str] = set()
    for hypothesis in hypotheses:
        hypothesis_id = str(hypothesis.get("hypothesis_id") or "").strip()
        if not hypothesis_id:
            failures.append("hypothesis_id: required")
            continue
        if hypothesis_id in known_hypotheses:
            failures.append(f"{hypothesis_id}: duplicate hypothesis_id")
        known_hypotheses.add(hypothesis_id)
        if hypothesis.get("not_source_grounded") is not True:
            failures.append(f"{hypothesis_id}: not_source_grounded must be true")
        if hypothesis.get("source_id") or hypothesis.get("source_span_id"):
            failures.append(
                f"{hypothesis_id}: hypothesis must not carry source-grounded fields"
            )
        derived = hypothesis.get("derived_from_claim_ids")
        if (
            not isinstance(derived, Sequence)
            or isinstance(derived, (str, bytes))
            or not derived
        ):
            failures.append(f"{hypothesis_id}: derived_from_claim_ids required")
            continue
        unknown = sorted(
            str(claim_id)
            for claim_id in derived
            if str(claim_id) not in known_claim_ids
        )
        if unknown:
            failures.append(
                f"{hypothesis_id}: unknown derived_from_claim_ids: {unknown}"
            )
    return (
        _record(
            "CLAIM-HYPOTHESIS-SEPARATION",
            HYPOTHESIS_PATHS,
            failures,
            {"hypothesis_count": len(hypotheses)},
        ),
        known_hypotheses,
    )


def _rule_pack_compiler_record(
    root_path: Path,
    claims_by_id: Mapping[str, Mapping[str, Any]],
    known_hypothesis_ids: set[str],
) -> ClaimGroundingValidationRecord:
    failures: list[str] = []
    checked_rule_count = 0
    for relative in RULE_PACK_PATHS:
        rule_pack, error = _read_json_object(root_path / relative, relative)
        if error:
            failures.append(error)
            continue
        rules = rule_pack.get("rules") if rule_pack else None
        if not isinstance(rules, Mapping) or not rules:
            failures.append(f"{relative}.rules: required object")
            continue
        for rule_id, rule in rules.items():
            checked_rule_count += 1
            if not isinstance(rule, Mapping):
                failures.append(f"{relative}.{rule_id}: rule must be object")
                continue
            claim_ids = rule.get("source_claim_ids")
            if (
                not isinstance(claim_ids, Sequence)
                or isinstance(claim_ids, (str, bytes))
                or not claim_ids
            ):
                failures.append(f"{rule_id}: source_claim_ids required")
            else:
                for claim_id in claim_ids:
                    claim = claims_by_id.get(str(claim_id))
                    if claim is None:
                        failures.append(
                            f"{rule_id}: unknown source_claim_id {claim_id}"
                        )
                    elif claim.get("verifier_status") != "passed":
                        failures.append(
                            f"{rule_id}: claim {claim_id} verifier_status must be passed"
                        )
            hypothesis_ids = rule.get("hypothesis_ids")
            if not isinstance(hypothesis_ids, Sequence) or isinstance(
                hypothesis_ids, (str, bytes)
            ):
                failures.append(f"{rule_id}: hypothesis_ids must be array")
            else:
                unknown = sorted(
                    str(hypothesis_id)
                    for hypothesis_id in hypothesis_ids
                    if str(hypothesis_id) not in known_hypothesis_ids
                )
                if unknown:
                    failures.append(f"{rule_id}: unknown hypothesis_ids: {unknown}")
            if rule.get("validation_required") is not True:
                failures.append(f"{rule_id}: validation_required must be true")
    return _record(
        "CLAIM-RULE-COMPILER-ELIGIBILITY",
        RULE_PACK_PATHS,
        failures,
        {"checked_rule_count": checked_rule_count},
    )


def build_claim_grounding_validation_report(
    root: str | Path = ".",
) -> ClaimGroundingValidationReport:
    root_path = Path(root)
    grounding_record, claims_by_id, known_claim_ids = _claim_grounding_record(root_path)
    hypothesis_record, known_hypothesis_ids = _hypothesis_separation_record(
        root_path,
        known_claim_ids,
    )
    compiler_record = _rule_pack_compiler_record(
        root_path,
        claims_by_id,
        known_hypothesis_ids,
    )
    return ClaimGroundingValidationReport(
        report_id="RKE-CLAIM-GROUNDING-VALIDATION-REPORT-20260606",
        records=(grounding_record, hypothesis_record, compiler_record),
    )


def write_claim_grounding_validation_report(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    report = build_claim_grounding_validation_report(root_path)
    return _write_json(
        root_path / CLAIM_GROUNDING_REPORT_PATH,
        {
            **asdict(report),
            "accepted": report.accepted,
            "failure_count": report.failure_count,
        },
    )
