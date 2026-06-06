"""Sector semiconductor sandbox demo for RKE Phase 5."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .p0 import (
    DataAvailabilityMatrix,
    Hypothesis,
    LearnableParameter,
    MetricProxyAvailability,
    Rule,
    RulePack,
    SourceGroundedClaim,
)
from .phase_minus1 import load_jsonl_with_errors
from .runtime import (
    EvidenceLedgerItem,
    ProgressEvent,
    RuntimeAgentOutput,
    RuntimeInference,
    RuntimeRecommendation,
)


@dataclass(frozen=True)
class DisagreementEvidence:
    claim_id: str
    stance: Literal["supportive", "risk", "valuation_risk", "uncertain"]
    topic: str
    source_id: str
    summary: str


@dataclass(frozen=True)
class DisagreementCluster:
    cluster_id: str
    topic: str
    supportive_claim_ids: Sequence[str]
    opposing_claim_ids: Sequence[str]
    risk_claim_ids: Sequence[str]
    resolution: str
    confidence_cap: float
    production_blockers: Sequence[str]


@dataclass(frozen=True)
class SectorSemiconductorDemoBundle:
    source_rows: Sequence[Mapping[str, Any]]
    claims: Sequence[SourceGroundedClaim]
    hypotheses: Sequence[Hypothesis]
    data_matrix: DataAvailabilityMatrix
    rule_pack: RulePack
    disagreement_evidence: Sequence[DisagreementEvidence]
    disagreement_cluster: DisagreementCluster
    runtime_output: RuntimeAgentOutput


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Sequence[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(_jsonable(row), ensure_ascii=False, sort_keys=True) + "\n")


def _short_hash(text: str) -> str:
    return "sha256:" + sha256(text.encode("utf-8")).hexdigest()[:16]


def _redacted_source_rows(bundle: SectorSemiconductorDemoBundle) -> tuple[dict[str, Any], ...]:
    claims_by_source: dict[str, list[SourceGroundedClaim]] = {}
    for claim in bundle.claims:
        claims_by_source.setdefault(claim.source_id, []).append(claim)

    rows: list[dict[str, Any]] = []
    for row in bundle.source_rows:
        source_id = str(row.get("source_id") or "")
        rows.append(
            {
                "source_id": source_id,
                "source_span_id": str(row.get("source_span_id") or ""),
                "source_type": str(row.get("source_type") or ""),
                "publish_date": str(row.get("publish_date") or ""),
                "discovered_at": str(row.get("discovered_at") or ""),
                "license_status": str(row.get("license_status") or ""),
                "point_in_time_available": row.get("point_in_time_available") is True,
                "source_hash": str(row.get("source_hash") or ""),
                "title": str(row.get("title") or ""),
                "institution": str(row.get("institution") or ""),
                "query_key": str(row.get("query_key") or ""),
                "report_type": str(row.get("report_type") or ""),
                "raw_source_ref": "registry/sources/tushare_research_reports.jsonl",
                "original_text_storage": "redacted_long_text_in_phase_minus_1_source_pool",
                "claim_span_previews": [
                    {
                        "claim_id": claim.claim_id,
                        "claim_text": claim.claim_text,
                        "source_text_hash": _short_hash(claim.claim_text),
                    }
                    for claim in sorted(claims_by_source.get(source_id, ()), key=lambda item: item.claim_id)
                ],
            }
        )
    return tuple(rows)


def _require_mapping_rows(rows: Sequence[Any], *, label: str) -> list[Mapping[str, Any]]:
    valid_rows: list[Mapping[str, Any]] = []
    invalid_rows: list[str] = []
    for index, row in enumerate(rows, 1):
        if isinstance(row, Mapping):
            valid_rows.append(row)
        else:
            invalid_rows.append(str(index))
    if invalid_rows:
        raise ValueError(f"{label} row(s) must be object: {', '.join(invalid_rows)}")
    return valid_rows


def _load_required_mapping_rows(path: str | Path, *, label: str) -> list[Mapping[str, Any]]:
    rows, parse_errors = load_jsonl_with_errors(path, label=label)
    if parse_errors:
        raise ValueError("; ".join(parse_errors))
    return _require_mapping_rows(rows, label=label)


def _find_report(rows: Sequence[Mapping[str, Any]], *, contains: str) -> Mapping[str, Any]:
    for row in rows:
        if row.get("query_key") == "半导体" and contains in str(row.get("abstract") or ""):
            return row
    raise ValueError(f"no semiconductor report contains required span: {contains}")


def _claim(
    *,
    claim_id: str,
    row: Mapping[str, Any],
    claim_text: str,
    cause_variables: Sequence[str],
    target_variables: Sequence[str],
    direction: Literal["positive", "negative", "neutral", "ambiguous"],
    claim_type: str = "causal_mechanism",
) -> SourceGroundedClaim:
    if claim_text not in str(row.get("abstract") or ""):
        raise ValueError(f"claim_text is not in source span: {claim_text}")
    return SourceGroundedClaim(
        claim_id=claim_id,
        source_id=str(row["source_id"]),
        source_span_id=str(row["source_span_id"]),
        claim_type=claim_type,
        claim_text=claim_text,
        cause_variables=tuple(cause_variables),
        target_variables=tuple(target_variables),
        direction=direction,
        extraction_confidence_bin="medium",
        verifier_status="passed",
        human_review_required=True,
    )


def build_sector_semiconductor_demo(
    source_rows: Sequence[Any] | None = None,
) -> SectorSemiconductorDemoBundle:
    rows = _require_mapping_rows(
        _load_required_mapping_rows(
            "registry/sources/tushare_research_reports.jsonl",
            label="semiconductor source",
        )
        if source_rows is None
        else source_rows,
        label="semiconductor source",
    )
    cycle_row = _find_report(rows, contains="存储市场仍保持较高景气度")
    valuation_row = _find_report(rows, contains="行业估值高于近年中枢水平")
    trade_risk_row = _find_report(rows, contains="中美科技摩擦加剧")

    claims = (
        _claim(
            claim_id="CLAIM-SEMI-20260605-0001",
            row=cycle_row,
            claim_text="存储市场仍保持较高景气度",
            cause_variables=("ai_compute_demand",),
            target_variables=("semiconductor_storage_cycle",),
            direction="positive",
        ),
        _claim(
            claim_id="CLAIM-SEMI-20260605-0002",
            row=valuation_row,
            claim_text="行业估值高于近年中枢水平",
            cause_variables=("valuation_percentile",),
            target_variables=("forward_alpha_after_policy_catalyst",),
            direction="negative",
            claim_type="failure_mode",
        ),
        _claim(
            claim_id="CLAIM-SEMI-20260605-0003",
            row=trade_risk_row,
            claim_text="中美科技摩擦加剧",
            cause_variables=("trade_friction_intensity",),
            target_variables=("semiconductor_policy_substitution_alpha",),
            direction="negative",
            claim_type="risk_factor",
        ),
    )
    hypotheses = (
        Hypothesis(
            hypothesis_id="HYP-SEMI-20260605-0001",
            derived_from_claim_ids=(claims[0].claim_id,),
            hypothesis_type="policy_substitution_transmission",
            statement=(
                "A policy-substitution theme may help semiconductor relative interest only "
                "after flow, order, or price confirmation."
            ),
            not_source_grounded=True,
            requires_validation=True,
            proposed_metric_proxies=(
                "semiconductor_policy_theme_mentions_20d",
                "semiconductor_etf_flow_20d",
                "semiconductor_relative_return_20d",
            ),
            status="draft",
        ),
        Hypothesis(
            hypothesis_id="HYP-SEMI-20260605-0002",
            derived_from_claim_ids=(claims[1].claim_id, claims[2].claim_id),
            hypothesis_type="failure_mode",
            statement="High valuation or external friction should cap any policy-substitution signal.",
            not_source_grounded=True,
            requires_validation=True,
            proposed_metric_proxies=("valuation_percentile_3y", "trade_friction_news_count_20d"),
            status="draft",
        ),
    )
    matrix = DataAvailabilityMatrix(
        matrix_id="DAM-SEMI-SANDBOX-2026Q2",
        proxies={
            "semiconductor_policy_theme_mentions_20d": MetricProxyAvailability(
                metric_proxy="semiconductor_policy_theme_mentions_20d",
                data_source="tushare_research_report_text_sandbox",
                point_in_time_available=True,
                history_start="2026-02-06",
                history_end="2026-06-05",
                vintage_handling="as_published",
                restatement_risk="low",
                survivorship_bias_risk="medium",
                timestamp_granularity="daily",
                allowed_for_validation=False,
                allowed_for_production=False,
                coverage_drift_risk="high",
                notes="Sandbox only until license review and historical text coverage audit pass.",
            ),
            "semiconductor_etf_flow_20d": MetricProxyAvailability(
                metric_proxy="semiconductor_etf_flow_20d",
                data_source="qlib_or_vendor_pit_flow",
                point_in_time_available=True,
                history_start="2005-01-01",
                history_end="2026-06-05",
                vintage_handling="as_reported",
                restatement_risk="low",
                survivorship_bias_risk="low",
                timestamp_granularity="daily",
                allowed_for_validation=True,
                allowed_for_production=True,
                coverage_drift_risk="low",
            ),
            "semiconductor_relative_return_20d": MetricProxyAvailability(
                metric_proxy="semiconductor_relative_return_20d",
                data_source="qlib_pit_prices",
                point_in_time_available=True,
                history_start="2005-01-01",
                history_end="2026-06-05",
                vintage_handling="as_reported",
                restatement_risk="low",
                survivorship_bias_risk="low",
                timestamp_granularity="daily",
                allowed_for_validation=True,
                allowed_for_production=True,
                coverage_drift_risk="low",
            ),
        },
    )
    rule = Rule(
        rule_id="sector.semiconductor.soft.014",
        rule_type="soft",
        status="candidate",
        source_claim_ids=tuple(claim.claim_id for claim in claims),
        hypothesis_ids=tuple(hypothesis.hypothesis_id for hypothesis in hypotheses),
        metric_proxies=(
            "semiconductor_policy_theme_mentions_20d",
            "semiconductor_etf_flow_20d",
            "semiconductor_relative_return_20d",
        ),
        mechanism_chain=(
            "policy_substitution_theme",
            "flow_or_price_confirmation",
            "semiconductor_relative_interest",
        ),
        horizon_days=(20, 60),
        learnable_parameters={
            "confirmation_window_days": LearnableParameter(
                value=20,
                type="integer",
                unit="trading_day",
                min=10,
                max=60,
            ),
            "confidence_cap": LearnableParameter(
                value=0.60,
                type="float",
                min=0.0,
                max=0.60,
            ),
        },
        validation_required=True,
        validation_status="sandbox_only",
    )
    rule_pack = RulePack(
        rule_pack_id="sector.semiconductor.policy_substitution.v1",
        agent_id="sector.semiconductor",
        status="candidate",
        rules={rule.rule_id: rule},
    )
    disagreement_evidence = (
        DisagreementEvidence(
            claim_id=claims[0].claim_id,
            stance="supportive",
            topic="semiconductor_policy_substitution",
            source_id=claims[0].source_id,
            summary="storage cycle support claim",
        ),
        DisagreementEvidence(
            claim_id=claims[1].claim_id,
            stance="valuation_risk",
            topic="semiconductor_policy_substitution",
            source_id=claims[1].source_id,
            summary="valuation above historical center risk",
        ),
        DisagreementEvidence(
            claim_id=claims[2].claim_id,
            stance="risk",
            topic="semiconductor_policy_substitution",
            source_id=claims[2].source_id,
            summary="trade friction risk",
        ),
    )
    disagreement_cluster = DisagreementCluster(
        cluster_id="DISAGREE-SEMI-POLICY-SUB-20260605",
        topic="semiconductor_policy_substitution",
        supportive_claim_ids=(claims[0].claim_id,),
        opposing_claim_ids=(),
        risk_claim_ids=(claims[1].claim_id, claims[2].claim_id),
        resolution=(
            "Keep as provenance demo; cap confidence at 0.60 and require flow or price confirmation."
        ),
        confidence_cap=0.60,
        production_blockers=(
            "sell-side research license_status=pending_review",
            "text proxy coverage drift is high",
            "no hardened validation experiment",
        ),
    )
    runtime_output = RuntimeAgentOutput(
        evidence_ledger=(
            EvidenceLedgerItem(
                evidence_id="E-SEMI-20260605-0001",
                source_type="source_grounded_claim",
                source_tool="tushare_research_report_sandbox",
                metric="semiconductor_policy_theme_mentions_20d",
                value="storage_cycle_support_with_risks",
                unit="theme",
                as_of="2026-06-05",
                freshness_days=0,
                direction="mixed",
                fallback=False,
                confidence_impact="capped",
                source_claim_ids=tuple(claim.claim_id for claim in claims),
            ),
        ),
        research_rule_ids_used=(rule.rule_id,),
        source_claim_ids_used=tuple(claim.claim_id for claim in claims),
        hypothesis_ids_used=tuple(hypothesis.hypothesis_id for hypothesis in hypotheses),
        inferences=(
            RuntimeInference(
                inference_id="I-SEMI-20260605-0001",
                statement="Semiconductor policy-substitution evidence is mixed and sandbox-only.",
                evidence_ids=("E-SEMI-20260605-0001",),
                rule_ids=(rule.rule_id,),
                source_claim_ids=tuple(claim.claim_id for claim in claims),
            ),
        ),
        recommendations=(
            RuntimeRecommendation(
                recommendation_id="R-SEMI-20260605-0001",
                statement="Monitor only until current flow or price confirmation exists.",
                inference_ids=("I-SEMI-20260605-0001",),
                confidence=0.50,
                actionability="monitor_only",
            ),
        ),
        uncertainties=(
            "sell-side report license is pending review",
            "risk claims require validation before any tilt",
        ),
        confidence_components={
            "data_confidence": 0.50,
            "research_confidence": 0.55,
            "empirical_validation_confidence": 0.30,
            "regime_match_confidence": 0.50,
        },
        rule_aggregation_summary={
            "has_opposing_rules": False,
            "correlated_rule_duplicate_count": 0,
            "confidence_cap": 0.60,
            "research_only": True,
        },
        downstream_handoff={
            "agent_id": "sector.semiconductor",
            "summary": "sandbox_monitor_only_policy_substitution_demo",
        },
        progress_event=ProgressEvent(
            agent_id="sector.semiconductor",
            layer="sector",
            status="completed",
            tools_used=("tushare_research_report_sandbox",),
            evidence_count=1,
            fallback_count=0,
            missing_count=0,
            schema_valid=True,
            confidence=0.50,
        ),
    )
    unique_sources = {str(row["source_id"]): row for row in (cycle_row, valuation_row, trade_risk_row)}
    return SectorSemiconductorDemoBundle(
        source_rows=tuple(unique_sources.values()),
        claims=claims,
        hypotheses=hypotheses,
        data_matrix=matrix,
        rule_pack=rule_pack,
        disagreement_evidence=disagreement_evidence,
        disagreement_cluster=disagreement_cluster,
        runtime_output=runtime_output,
    )


def write_sector_semiconductor_demo_registry(root: str | Path = ".") -> dict[str, str]:
    root_path = Path(root)
    bundle = build_sector_semiconductor_demo(
        _load_required_mapping_rows(
            root_path / "registry/sources/tushare_research_reports.jsonl",
            label="semiconductor source",
        )
    )
    outputs = {
        "sources": root_path / "registry/sources/semiconductor_demo_sources.jsonl",
        "claims": root_path / "registry/claims/semiconductor_claims.jsonl",
        "hypotheses": root_path / "registry/hypotheses/semiconductor_hypotheses.jsonl",
        "data_availability": root_path
        / "registry/data_availability/semiconductor_sandbox_data_availability.json",
        "rule_pack": root_path / "registry/rule_packs/sector.semiconductor.policy_substitution.v1.json",
        "disagreement": root_path / "registry/disagreement/semiconductor_policy_substitution.json",
        "runtime_output": root_path
        / "registry/runtime_outputs/sector.semiconductor.demo.20260605.json",
    }
    _write_jsonl(outputs["sources"], _redacted_source_rows(bundle))
    _write_jsonl(outputs["claims"], bundle.claims)
    _write_jsonl(outputs["hypotheses"], bundle.hypotheses)
    _write_json(outputs["data_availability"], bundle.data_matrix)
    _write_json(
        outputs["rule_pack"],
        {
            **_jsonable(bundle.rule_pack),
            "demo_status": "sandbox",
            "empirical_confidence_bin": "low",
            "production_allowed": False,
        },
    )
    _write_json(
        outputs["disagreement"],
        {
            "evidence": bundle.disagreement_evidence,
            "cluster": bundle.disagreement_cluster,
        },
    )
    _write_json(
        outputs["runtime_output"],
        {"agent_output_id": "OUT-SEMI-20260605-0001", **_jsonable(bundle.runtime_output)},
    )
    return {key: str(path) for key, path in outputs.items()}


def main() -> None:
    print(json.dumps(write_sector_semiconductor_demo_registry(Path.cwd()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
