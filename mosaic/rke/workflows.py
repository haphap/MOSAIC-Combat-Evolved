"""End-to-end RKE refresh workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .central_bank_mvp import write_central_bank_mvp_registry
from .claim_vocabulary import write_claim_variable_validation_report, write_claim_variable_vocabulary
from .completion_auditor import write_completion_audit
from .compliance import write_source_license_review_template
from .dashboard_reports import write_dashboard_reports
from .gold_candidate_claims import write_gold_candidate_claims
from .gold_review_packet import write_gold_review_packet
from .license_review_packet import write_license_review_packet
from .macro_expansion import write_macro_expansion_registry
from .master_plan_coverage import write_master_plan_coverage_report
from .phase_minus1 import load_jsonl, write_gold_set_review_template
from .policy_doc_validation import write_policy_doc_validation_report
from .prompt_asset_validation import write_prompt_asset_validation_report
from .registry_manifest import write_registry_manifest
from .review_gates import write_gold_set_review_summary, write_source_license_review_summary
from .schema_validation import write_schema_validation_report
from .sector_demo import write_sector_semiconductor_demo_registry
from .source_registry_validation import write_source_registry_validation_report
from .validation_hardening import (
    write_statistical_significance_report,
    write_validation_hardening_report,
)


@dataclass(frozen=True)
class RkeRefreshResult:
    root: str
    outputs: Mapping[str, str]
    manifest_valid: bool


def run_full_rke_refresh(
    root: str | Path = ".",
    *,
    preserve_review_templates: bool = True,
) -> RkeRefreshResult:
    root_path = Path(root)
    source_path = root_path / "registry/sources/tushare_research_reports.jsonl"
    gold_candidates_path = root_path / "registry/sources/tushare_research_reports.gold_candidates.jsonl"
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    if not gold_candidates_path.exists():
        raise FileNotFoundError(gold_candidates_path)

    outputs: dict[str, str] = {}
    for prefix, writer_outputs in (
        ("central_bank", write_central_bank_mvp_registry(root_path)),
        ("sector_semiconductor", write_sector_semiconductor_demo_registry(root_path)),
        ("macro_expansion", write_macro_expansion_registry(root_path)),
    ):
        outputs.update({f"{prefix}.{key}": value for key, value in writer_outputs.items()})

    gold_review_path = root_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    if not preserve_review_templates or not gold_review_path.exists():
        gold_rows = load_jsonl(gold_candidates_path)
        result = write_gold_set_review_template(gold_rows, gold_review_path, claims_per_document=10)
        outputs["gold_set_review_template"] = str(result["path"])

    license_review_path = root_path / "registry/compliance/tushare_license_review_template.jsonl"
    if not preserve_review_templates or not license_review_path.exists():
        source_rows = load_jsonl(source_path)
        result = write_source_license_review_template(source_rows, license_review_path)
        outputs["license_review_template"] = str(result["path"])

    gold_summary = write_gold_set_review_summary(root_path)
    license_summary = write_source_license_review_summary(root_path)
    license_packet = write_license_review_packet(root_path)
    claim_vocabulary = write_claim_variable_vocabulary(root_path)
    gold_candidate_claims = write_gold_candidate_claims(root_path)
    gold_packet = write_gold_review_packet(root_path)
    claim_variable_summary = write_claim_variable_validation_report(root_path)
    source_validation = write_source_registry_validation_report(root_path)
    schema_summary = write_schema_validation_report(root_path)
    validation_hardening = write_validation_hardening_report(root_path)
    statistical_significance = write_statistical_significance_report(root_path)
    prompt_asset_summary = write_prompt_asset_validation_report(root_path)
    policy_doc_summary = write_policy_doc_validation_report(root_path)
    audit_result = write_completion_audit(root_path)
    master_plan_coverage = write_master_plan_coverage_report(root_path)
    dashboard_outputs = write_dashboard_reports(root_path)
    manifest_result = write_registry_manifest(root_path)
    outputs["gold_set_review_summary"] = str(gold_summary["path"])
    outputs["gold_review_packet.json"] = gold_packet["json"]
    outputs["gold_review_packet.markdown"] = gold_packet["markdown"]
    outputs["license_review_summary"] = str(license_summary["path"])
    outputs["license_review_packet.json"] = license_packet["json"]
    outputs["license_review_packet.markdown"] = license_packet["markdown"]
    outputs["claim_variable_vocabulary"] = str(claim_vocabulary["path"])
    outputs["gold_candidate_claims"] = gold_candidate_claims["candidate_claims"]
    outputs["gold_candidate_claims_summary"] = gold_candidate_claims["summary"]
    outputs["claim_variable_validation_report"] = str(claim_variable_summary["path"])
    outputs["source_registry_validation_report"] = str(source_validation["path"])
    outputs["schema_validation_report"] = str(schema_summary["path"])
    outputs["validation_hardening_report"] = str(validation_hardening["path"])
    outputs["statistical_significance_report"] = str(statistical_significance["path"])
    outputs["prompt_asset_validation_report"] = str(prompt_asset_summary["path"])
    outputs["policy_doc_validation_report"] = str(policy_doc_summary["path"])
    outputs["completion_audit"] = str(audit_result["path"])
    outputs["master_plan_coverage_report"] = str(master_plan_coverage["path"])
    outputs.update({f"dashboard.{key}": value for key, value in dashboard_outputs.items()})
    outputs["registry_manifest"] = str(manifest_result["path"])
    return RkeRefreshResult(
        root=str(root_path),
        outputs=outputs,
        manifest_valid=bool(manifest_result["valid"]),
    )
