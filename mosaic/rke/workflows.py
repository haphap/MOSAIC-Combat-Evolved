"""End-to-end RKE refresh workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .audit_viewer import write_audit_trace_view
from .central_bank_mvp import write_central_bank_mvp_registry
from .claim_grounding_validation import write_claim_grounding_validation_report
from .claim_vocabulary import (
    write_claim_variable_validation_report,
    write_claim_variable_vocabulary,
)
from .completion_auditor import write_completion_audit
from .compliance import write_source_license_review_template
from .dashboard_reports import write_dashboard_reports
from .gold_candidate_claims import write_gold_candidate_claims
from .gold_review_packet import write_gold_review_packet
from .license_review_packet import write_license_review_packet
from .macro_expansion import write_macro_expansion_registry
from .manual_review_batches import write_manual_review_batches
from .operator_handoff import write_operator_handoff
from .operator_readiness import write_operator_readiness_report
from .master_plan_coverage import write_master_plan_coverage_report
from .monitoring_diagnostics import write_production_monitor_diagnostics
from .phase_minus1 import load_jsonl_with_errors, write_gold_set_review_template
from .policy_doc_validation import write_policy_doc_validation_report
from .prompt_asset_validation import write_prompt_asset_validation_report
from .promotion_gate import write_production_promotion_gate_report
from .registry_manifest import write_registry_manifest
from .review_gates import (
    write_gold_set_review_summary,
    write_source_license_review_summary,
)
from .rollback_readiness import write_rollback_readiness_report
from .schema_validation import write_schema_validation_report
from .sector_demo import write_sector_semiconductor_demo_registry
from .source_registry_validation import write_source_registry_validation_report
from .source_text_redaction import write_source_text_redaction_report
from .validation_hardening import (
    write_statistical_significance_report,
    write_validation_hardening_report,
)


@dataclass(frozen=True)
class RkeRefreshResult:
    root: str
    outputs: Mapping[str, str]
    manifest_valid: bool


def _require_mapping_rows(rows: list[Any], *, label: str) -> list[Mapping[str, Any]]:
    valid_rows: list[Mapping[str, Any]] = []
    invalid_rows: list[str] = []
    for index, row in enumerate(rows, 1):
        if isinstance(row, Mapping):
            valid_rows.append(row)
        else:
            invalid_rows.append(str(index))
    if invalid_rows:
        raise ValueError(
            f"{label} row must be object at row(s): {', '.join(invalid_rows)}"
        )
    return valid_rows


def _load_required_mapping_rows(path: Path, *, label: str) -> list[Mapping[str, Any]]:
    rows, parse_errors = load_jsonl_with_errors(path, label=label)
    blockers = list(parse_errors)
    try:
        valid_rows = _require_mapping_rows(rows, label=label)
    except ValueError as exc:
        valid_rows = []
        blockers.append(str(exc))
    if blockers:
        raise ValueError("; ".join(blockers))
    return valid_rows


def run_full_rke_refresh(
    root: str | Path = ".",
    *,
    preserve_review_templates: bool = True,
) -> RkeRefreshResult:
    root_path = Path(root)
    source_path = root_path / "registry/sources/tushare_research_reports.jsonl"
    gold_candidates_path = (
        root_path / "registry/sources/tushare_research_reports.gold_candidates.jsonl"
    )
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
        outputs.update(
            {f"{prefix}.{key}": value for key, value in writer_outputs.items()}
        )

    gold_review_path = (
        root_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    )
    if not preserve_review_templates or not gold_review_path.exists():
        gold_rows = _load_required_mapping_rows(
            gold_candidates_path, label="gold candidate"
        )
        result = write_gold_set_review_template(
            gold_rows, gold_review_path, claims_per_document=10
        )
        outputs["gold_set_review_template"] = str(result["path"])

    license_review_path = (
        root_path / "registry/compliance/tushare_license_review_template.jsonl"
    )
    if not preserve_review_templates or not license_review_path.exists():
        source_rows = _load_required_mapping_rows(source_path, label="source registry")
        result = write_source_license_review_template(source_rows, license_review_path)
        outputs["license_review_template"] = str(result["path"])

    gold_summary = write_gold_set_review_summary(root_path)
    license_summary = write_source_license_review_summary(root_path)
    license_packet = write_license_review_packet(root_path)
    review_batches = write_manual_review_batches(root_path)
    claim_vocabulary = write_claim_variable_vocabulary(root_path)
    gold_candidate_claims = write_gold_candidate_claims(root_path)
    gold_packet = write_gold_review_packet(root_path)
    claim_variable_summary = write_claim_variable_validation_report(root_path)
    claim_grounding_summary = write_claim_grounding_validation_report(root_path)
    source_validation = write_source_registry_validation_report(root_path)
    schema_summary = write_schema_validation_report(root_path)
    validation_hardening = write_validation_hardening_report(root_path)
    statistical_significance = write_statistical_significance_report(root_path)
    monitoring_diagnostics = write_production_monitor_diagnostics(root_path)
    prompt_asset_summary = write_prompt_asset_validation_report(root_path)
    policy_doc_summary = write_policy_doc_validation_report(root_path)
    source_text_redaction = write_source_text_redaction_report(root_path)
    audit_trace_view = write_audit_trace_view(root_path)
    audit_result = write_completion_audit(root_path)
    promotion_gate = write_production_promotion_gate_report(root_path)
    operator_handoff = write_operator_handoff(root_path)
    rollback_readiness = write_rollback_readiness_report(root_path)
    operator_readiness = write_operator_readiness_report(root_path)
    master_plan_coverage = write_master_plan_coverage_report(root_path)
    dashboard_outputs = write_dashboard_reports(root_path)
    manifest_result = write_registry_manifest(root_path)
    outputs["gold_set_review_summary"] = str(gold_summary["path"])
    outputs["gold_review_packet.json"] = gold_packet["json"]
    outputs["gold_review_packet.markdown"] = gold_packet["markdown"]
    outputs["license_review_summary"] = str(license_summary["path"])
    outputs["license_review_packet.json"] = license_packet["json"]
    outputs["license_review_packet.markdown"] = license_packet["markdown"]
    outputs["manual_review_batch_status"] = review_batches["status"]
    outputs["manual_review_gold_set_import_template"] = review_batches[
        "gold_set_import_template"
    ]
    outputs["manual_review_gold_set_full_import_template"] = review_batches[
        "gold_set_full_import_template"
    ]
    outputs["manual_review_gold_set_workbook"] = review_batches[
        "gold_set_review_workbook"
    ]
    outputs["manual_review_source_license_import_template"] = review_batches[
        "source_license_import_template"
    ]
    outputs["manual_review_source_license_workbook"] = review_batches[
        "source_license_review_workbook"
    ]
    outputs["manual_review_progress_report"] = operator_handoff[
        "manual_review_progress_report"
    ]
    outputs["manual_review_runbook"] = operator_handoff["manual_review_runbook"]
    outputs["claim_variable_vocabulary"] = str(claim_vocabulary["path"])
    outputs["gold_candidate_claims"] = gold_candidate_claims["candidate_claims"]
    outputs["gold_candidate_claims_summary"] = gold_candidate_claims["summary"]
    outputs["claim_variable_validation_report"] = str(claim_variable_summary["path"])
    outputs["claim_grounding_validation_report"] = str(claim_grounding_summary["path"])
    outputs["source_registry_validation_report"] = str(source_validation["path"])
    outputs["schema_validation_report"] = str(schema_summary["path"])
    outputs["validation_hardening_report"] = str(validation_hardening["path"])
    outputs["statistical_significance_report"] = str(statistical_significance["path"])
    outputs["production_monitor_diagnostics"] = str(monitoring_diagnostics["path"])
    outputs["prompt_asset_validation_report"] = str(prompt_asset_summary["path"])
    outputs["policy_doc_validation_report"] = str(policy_doc_summary["path"])
    outputs["source_text_redaction_report"] = str(source_text_redaction["path"])
    outputs["audit_trace_view.json"] = audit_trace_view["json"]
    outputs["audit_trace_view.markdown"] = audit_trace_view["markdown"]
    outputs["completion_audit"] = str(audit_result["path"])
    outputs["production_promotion_gate"] = str(promotion_gate["path"])
    outputs["operator_handoff.json"] = operator_handoff["json"]
    outputs["operator_handoff.markdown"] = operator_handoff["markdown"]
    outputs["lockbox_review_import_template"] = operator_handoff[
        "lockbox_import_template"
    ]
    outputs["lockbox_review_import_report"] = (
        "registry/lockbox/central_bank_lockbox_review_import_report.json"
    )
    outputs["gold_set_full_import_template"] = operator_handoff[
        "gold_set_full_import_template"
    ]
    outputs["gold_review_import_report"] = (
        "registry/gold_sets/tushare_research_reports.review_import_report.json"
    )
    outputs["source_license_policy_template"] = operator_handoff[
        "source_license_policy_template"
    ]
    outputs["source_license_review_workbook"] = operator_handoff[
        "source_license_review_workbook"
    ]
    outputs["rollback_readiness_report"] = str(rollback_readiness["path"])
    outputs["operator_readiness_report"] = str(operator_readiness["path"])
    outputs["source_license_policy_import_report"] = (
        "registry/review_batches/source_license_policy_import_report.json"
    )
    outputs["manual_review_bundle_manifest"] = (
        "registry/review_batches/manual_review_bundle_manifest.json"
    )
    outputs["promotion_dry_run_report"] = (
        "registry/promotion/rke_promotion_dry_run_report.json"
    )
    outputs["master_plan_coverage_report"] = str(master_plan_coverage["path"])
    outputs.update(
        {f"dashboard.{key}": value for key, value in dashboard_outputs.items()}
    )
    outputs["registry_manifest"] = str(manifest_result["path"])
    return RkeRefreshResult(
        root=str(root_path),
        outputs=outputs,
        manifest_valid=bool(manifest_result["valid"]),
    )
