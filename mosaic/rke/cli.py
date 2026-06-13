"""Command-line entry points for RKE registry operations."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Sequence

from .audit_viewer import build_audit_trace_view, write_audit_trace_view
from .claim_vocabulary import (
    build_claim_variable_validation_report,
    write_claim_variable_validation_report,
)
from .claim_grounding_validation import (
    write_claim_grounding_validation_report,
)
from .completion_auditor import write_completion_audit
from .dashboard_reports import write_dashboard_reports
from .experiment_validation import (
    build_experiment_validation_report,
    write_experiment_validation_report,
)
from .gold_candidate_claims import (
    write_gold_candidate_claims,
)
from .gold_review_packet import build_gold_review_packet, write_gold_review_packet
from .license_review_packet import (
    build_license_review_packet,
    write_license_review_packet,
)
from .license_policy_import import (
    SOURCE_LICENSE_REVIEWED_POLICY_PATH,
    build_source_license_policy_import,
    write_source_license_reviewed_policy_starter,
)
from .lockbox_review_import import apply_lockbox_review_import
from .manual_review_import import (
    apply_gold_set_review_import,
    apply_source_license_review_import,
)
from .manual_review_batches import (
    GOLD_FULL_REVIEWED_IMPORT_PATH,
    GOLD_REVIEWED_IMPORT_PATH,
    build_manual_review_batch_status,
    write_gold_review_evidence,
    write_gold_review_starter,
    write_manual_review_batches,
)
from .operator_handoff import (
    LOCKBOX_REVIEWED_IMPORT_PATH,
    build_operator_handoff,
    lockbox_upstream_review_blockers,
    write_lockbox_review_starter,
    write_operator_handoff,
)
from .operator_readiness import (
    build_operator_readiness_report,
    write_operator_readiness_report,
)
from .master_plan_coverage import (
    build_master_plan_coverage_report,
    write_master_plan_coverage_report,
)
from .monitoring_diagnostics import (
    build_production_monitor_diagnostics,
    write_production_monitor_diagnostics,
)
from .rollback_readiness import (
    build_rollback_readiness_report,
    write_rollback_readiness_report,
)
from .policy_doc_validation import (
    build_policy_doc_validation_report,
    write_policy_doc_validation_report,
)
from .prompt_asset_validation import (
    build_prompt_asset_validation_report,
    write_prompt_asset_validation_report,
)
from .promotion_gate import (
    build_production_promotion_gate_report,
    write_production_promotion_gate_report,
)
from .promotion_dry_run import (
    build_promotion_dry_run_report,
    write_promotion_dry_run_report,
)
from .rule_pack_validation import (
    build_rule_pack_validation_report,
    write_rule_pack_validation_report,
)
from .registry_manifest import (
    build_registry_manifest,
    validate_required_registry,
    validate_required_registry_content,
    write_registry_manifest,
)
from .report_intelligence import (
    ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
    ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH,
    DEFAULT_VLLM_TIMEOUT_SECONDS,
    ReportIntelligenceConfig,
    apply_analytical_footprint_review_import,
    merge_report_intelligence_batch_outputs,
    prepare_analytical_footprint_review_import,
    run_report_intelligence_refresh,
    write_analytical_footprint_review_assist,
    write_analytical_footprint_review_evidence,
    write_report_intelligence_evolution_readiness_gate,
    write_report_intelligence_prompt_mutation_candidates,
)
from .review_progress import (
    build_manual_review_progress_summary,
    build_manual_review_progress,
    write_manual_review_progress_report,
    write_manual_review_runbook,
)
from .review_gates import (
    summarize_gold_set_review,
    summarize_source_license_review,
    write_gold_set_review_summary,
    write_source_license_review_summary,
)
from .schema_validation import (
    build_schema_validation_report,
    write_schema_validation_report,
)
from .source_registry_validation import (
    build_source_registry_validation_report,
    write_source_registry_validation_report,
)
from .source_text_redaction import (
    build_source_text_redaction_report,
    write_source_text_redaction_report,
)
from .tushare_reports import (
    P9_REPORT_INTELLIGENCE_CORPUS_PROFILE,
    refresh_tushare_research_report_registry,
)
from .validation_hardening import (
    build_central_bank_statistical_significance_report,
    build_central_bank_validation_hardening_report,
    write_statistical_significance_report,
    write_validation_hardening_report,
)
from .workflows import run_full_rke_refresh


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _print_json(payload: Any) -> None:
    print(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True))


def _sampled_sequence(
    values: Sequence[Any], *, sample_size: int = 10
) -> dict[str, Any]:
    items = list(values)
    return {
        "count": len(items),
        "sample": items[:sample_size],
        "truncated": len(items) > sample_size,
    }


def _source_license_status_stdout(summary: Any) -> dict[str, Any]:
    payload = asdict(summary)
    missing = payload.pop("missing_review_source_ids", ())
    extra = payload.pop("extra_review_source_ids", ())
    payload["missing_review_source_ids"] = _sampled_sequence(missing)
    payload["extra_review_source_ids"] = _sampled_sequence(extra)
    payload["full_summary_path"] = (
        "registry/compliance/tushare_license_review_summary.json"
    )
    return payload


def _load_env_file(path: str | None) -> None:
    if not path:
        return
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError("python-dotenv is required to load --env-file") from exc
    load_dotenv(path, override=False)


def _split_repeated_csv(values: Sequence[str] | None) -> tuple[str, ...]:
    if not values:
        return ()
    out: list[str] = []
    for value in values:
        out.extend(item.strip() for item in value.split(",") if item.strip())
    return tuple(out)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mosaic-rke")
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh = subparsers.add_parser(
        "refresh", help="Regenerate local RKE registry artifacts."
    )
    refresh.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    refresh.add_argument(
        "--overwrite-review-templates",
        action="store_true",
        help="Regenerate gold-set and license review templates even when they exist.",
    )

    manifest = subparsers.add_parser("manifest", help="Write the registry manifest.")
    manifest.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    audit = subparsers.add_parser("audit", help="Recompute completion audit.")
    audit.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    audit_view = subparsers.add_parser(
        "audit-view",
        help="Write and print the central-bank source-to-output audit trace viewer.",
    )
    audit_view.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    master_plan_status = subparsers.add_parser(
        "master-plan-status",
        help="Write and print the master-plan coverage audit.",
    )
    master_plan_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    dashboard = subparsers.add_parser(
        "dashboard", help="Write dashboard JSON and Markdown reports."
    )
    dashboard.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    policy_doc_status = subparsers.add_parser(
        "policy-doc-status",
        help="Write and print the RKE policy documentation validation report.",
    )
    policy_doc_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    schema_status = subparsers.add_parser(
        "schema-status",
        help="Write and print the Phase 1 schema validation report.",
    )
    schema_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    schema_status.add_argument(
        "--failures-only",
        action="store_true",
        help="Print only schema records that failed validation.",
    )
    schema_status.add_argument(
        "--no-write",
        action="store_true",
        help="Do not rewrite schema validation report artifacts.",
    )

    rule_pack_status = subparsers.add_parser(
        "rule-pack-status",
        help="Write and print the rule-pack validation report.",
    )
    rule_pack_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    prompt_status = subparsers.add_parser(
        "prompt-status",
        help="Write and print the rendered prompt asset validation report.",
    )
    prompt_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    claim_status = subparsers.add_parser(
        "claim-status",
        help="Write and print the claim variable vocabulary validation report.",
    )
    claim_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    source_status = subparsers.add_parser(
        "source-status",
        help="Write and print the source registry validation report.",
    )
    source_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    source_text_status = subparsers.add_parser(
        "source-text-status",
        help="Write and print the Tushare source-text redaction audit report.",
    )
    source_text_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    validation_status = subparsers.add_parser(
        "validation-status",
        help="Write and print the validation-hardening and statistical-significance reports.",
    )
    validation_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    experiment_status = subparsers.add_parser(
        "experiment-status",
        help="Write and print the hardened experiment-governance validation report.",
    )
    experiment_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    monitoring_diagnostics = subparsers.add_parser(
        "monitoring-diagnostics",
        help="Write and print production-monitor diagnostic scenarios.",
    )
    monitoring_diagnostics.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    rollback_readiness = subparsers.add_parser(
        "rollback-readiness",
        help="Write and print soft/hard/compliance rollback readiness checks.",
    )
    rollback_readiness.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    promotion_status = subparsers.add_parser(
        "promotion-status",
        help="Write and print the production-promotion gate report.",
    )
    promotion_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    promotion_dry_run = subparsers.add_parser(
        "promotion-dry-run",
        help="Simulate reviewed gold/footprint/license/lockbox inputs without mutating the registry.",
    )
    promotion_dry_run.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    promotion_dry_run.add_argument(
        "--gold-input", help="Reviewed gold-set JSONL input."
    )
    promotion_dry_run.add_argument(
        "--license-input", help="Reviewed source-license JSONL input."
    )
    promotion_dry_run.add_argument(
        "--footprint-input", help="Reviewed analytical-footprint JSONL input."
    )
    promotion_dry_run.add_argument(
        "--lockbox-input", help="Reviewed lockbox JSON input."
    )
    promotion_dry_run.add_argument(
        "--write-report",
        action="store_true",
        help="Write registry/promotion/rke_promotion_dry_run_report.json.",
    )

    gold_status = subparsers.add_parser(
        "gold-set-status",
        help="Write and print the manual gold-set review gate summary.",
    )
    gold_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    gold_packet = subparsers.add_parser(
        "gold-review-packet",
        help="Write and print the Phase -1 gold-set manual review packet summary.",
    )
    gold_packet.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    gold_candidate_claims = subparsers.add_parser(
        "gold-candidate-claims",
        help="Write and print deterministic source-bound candidate claims for gold-set review.",
    )
    gold_candidate_claims.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    license_status = subparsers.add_parser(
        "license-status",
        help="Write and print the source license review gate summary.",
    )
    license_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    license_packet = subparsers.add_parser(
        "license-review-packet",
        help="Write and print the source license manual review packet summary.",
    )
    license_packet.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    apply_gold_review = subparsers.add_parser(
        "apply-gold-review",
        help="Validate and apply a JSONL manual gold-set review import.",
    )
    apply_gold_review.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    apply_gold_review.add_argument(
        "--input", required=True, help="JSONL file containing reviewed gold-set rows."
    )
    apply_gold_review.add_argument(
        "--dry-run", action="store_true", help="Validate without changing review rows."
    )

    prepare_gold_review = subparsers.add_parser(
        "prepare-gold-review",
        help="Write a reviewer-editable gold-set JSONL starter without overwriting existing reviews.",
    )
    prepare_gold_review.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    prepare_gold_review.add_argument(
        "--output",
        help=(
            f"Reviewed gold-set output path. Defaults to {GOLD_REVIEWED_IMPORT_PATH}, "
            f"or {GOLD_FULL_REVIEWED_IMPORT_PATH} with --full."
        ),
    )
    prepare_gold_review.add_argument(
        "--full",
        action="store_true",
        help="Export all pending gold-set rows instead of the next batch.",
    )
    prepare_gold_review.add_argument(
        "--gold-batch-size",
        type=int,
        default=50,
        help="Rows for the next-batch starter when --full is not used. Defaults to 50.",
    )
    prepare_gold_review.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Pending-row offset when --full is not used. Use with --gold-batch-size for review batches.",
    )
    prepare_gold_review.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing reviewed gold-set starter.",
    )
    prepare_gold_review.add_argument(
        "--reviewer",
        default="",
        help="Optional reviewer name to prefill in each starter row.",
    )
    prepare_gold_review.add_argument(
        "--review-date",
        default="",
        help="Optional YYYY-MM-DD review date to prefill in each starter row.",
    )

    write_gold_review_evidence = subparsers.add_parser(
        "write-gold-review-evidence",
        help="Write private gold-set evidence snippets and draft review suggestions.",
    )
    write_gold_review_evidence.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    write_gold_review_evidence.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum pending rows to include. Defaults to 50.",
    )
    write_gold_review_evidence.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Pending-row offset after priority sorting. Use with --limit for review batches.",
    )
    write_gold_review_evidence.add_argument(
        "--review-input",
        help=(
            "Optional reviewed JSONL scratch file. When set, evidence rows follow "
            "this input order and are matched back to the full gold review template."
        ),
    )

    apply_license_review = subparsers.add_parser(
        "apply-license-review",
        help="Validate and apply a JSONL source-license review import.",
    )
    apply_license_review.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    apply_license_review.add_argument(
        "--input", required=True, help="JSONL file containing source license decisions."
    )
    apply_license_review.add_argument(
        "--dry-run", action="store_true", help="Validate without changing review rows."
    )

    build_license_import = subparsers.add_parser(
        "build-license-review-import",
        help="Expand a signed source-license policy JSON into an apply-license-review JSONL input.",
    )
    build_license_import.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    build_license_import.add_argument(
        "--policy",
        required=True,
        help="JSON policy file with reviewer/date, decisions, and filters.",
    )
    build_license_import.add_argument(
        "--output",
        default="registry/review_batches/source_license_policy_import.jsonl",
        help="Output JSONL path. Defaults to registry/review_batches/source_license_policy_import.jsonl.",
    )
    build_license_import.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report without writing output JSONL.",
    )

    prepare_license_policy = subparsers.add_parser(
        "prepare-license-policy-review",
        help="Write a reviewer-editable source-license policy starter without overwriting existing reviews.",
    )
    prepare_license_policy.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    prepare_license_policy.add_argument(
        "--output",
        default=SOURCE_LICENSE_REVIEWED_POLICY_PATH,
        help=f"Reviewed policy output path. Defaults to {SOURCE_LICENSE_REVIEWED_POLICY_PATH}.",
    )
    prepare_license_policy.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing reviewed policy starter.",
    )

    apply_lockbox_review = subparsers.add_parser(
        "apply-lockbox-review",
        help="Validate and apply a JSON lockbox review record.",
    )
    apply_lockbox_review.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    apply_lockbox_review.add_argument(
        "--input", required=True, help="JSON file containing one lockbox review record."
    )
    apply_lockbox_review.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without changing the lockbox record.",
    )
    apply_lockbox_review.add_argument(
        "--allow-pending-upstream",
        action="store_true",
        help=(
            "Allow validating or applying the lockbox review before gold-set, "
            "analytical-footprint, and source-license gates are ready."
        ),
    )

    prepare_lockbox_review = subparsers.add_parser(
        "prepare-lockbox-review",
        help="Write a reviewer-editable lockbox JSON starter without overwriting existing reviews.",
    )
    prepare_lockbox_review.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    prepare_lockbox_review.add_argument(
        "--output",
        default=LOCKBOX_REVIEWED_IMPORT_PATH,
        help=f"Reviewed lockbox output path. Defaults to {LOCKBOX_REVIEWED_IMPORT_PATH}.",
    )
    prepare_lockbox_review.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing reviewed lockbox starter.",
    )
    prepare_lockbox_review.add_argument(
        "--allow-pending-upstream",
        action="store_true",
        help=(
            "Allow writing the lockbox starter before gold-set, "
            "analytical-footprint, and source-license gates are ready."
        ),
    )

    review_batches = subparsers.add_parser(
        "review-batches",
        help="Write next-batch import templates for manual gold-set and source-license reviews.",
    )
    review_batches.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    review_batches.add_argument(
        "--gold-batch-size",
        type=int,
        default=50,
        help="Number of pending gold-set review rows to export. Defaults to 50.",
    )
    review_batches.add_argument(
        "--license-batch-size",
        type=int,
        default=50,
        help="Number of pending source-license review rows to export. Defaults to 50.",
    )

    operator_handoff = subparsers.add_parser(
        "operator-handoff",
        help="Write and print the remaining manual gate handoff package.",
    )
    operator_handoff.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    operator_readiness = subparsers.add_parser(
        "operator-readiness",
        help="Write and print operator handoff bundle integrity checks.",
    )
    operator_readiness.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    review_progress = subparsers.add_parser(
        "review-progress",
        help="Check reviewer-edited scratch files without mutating the working registry.",
    )
    review_progress.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    review_progress.add_argument(
        "--summary",
        action="store_true",
        help=(
            "Print a compact public-safe summary instead of the full gate and "
            "batch plan payload."
        ),
    )
    review_progress.add_argument(
        "--no-write",
        action="store_true",
        help=(
            "Do not rewrite manual review progress or runbook artifacts; print "
            "the current in-memory check result only."
        ),
    )
    review_progress.add_argument(
        "--review-kind",
        action="append",
        choices=("gold_set", "footprint_review", "source_license", "lockbox"),
        help=(
            "Limit --summary output to one review kind. May be repeated. "
            "Requires --summary."
        ),
    )

    fetch_reports = subparsers.add_parser(
        "fetch-tushare-reports",
        help="Fetch Tushare research reports and refresh dependent Phase -1 registry artifacts.",
    )
    fetch_reports.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    fetch_reports.add_argument(
        "--start-date", help="Inclusive YYYY-MM-DD query start date."
    )
    fetch_reports.add_argument(
        "--end-date", help="Inclusive YYYY-MM-DD query end date."
    )
    fetch_reports.add_argument(
        "--input-path",
        help=(
            "Local Tushare research_report CSV/JSONL to import instead of calling Tushare. "
            "When omitted, --start-date/--end-date and a query target are required."
        ),
    )
    fetch_reports.add_argument(
        "--stock-code",
        action="append",
        dest="stock_codes",
        help="Tushare stock code. May be repeated or comma-separated.",
    )
    fetch_reports.add_argument(
        "--industry-keyword",
        action="append",
        dest="industry_keywords",
        help="Tushare industry keyword. May be repeated or comma-separated.",
    )
    fetch_reports.add_argument(
        "--report-type",
        action="append",
        dest="report_types",
        help=(
            "Tushare report_type to query across the whole market by date window. "
            "May be repeated or comma-separated, e.g. 行业研报,个股研报."
        ),
    )
    fetch_reports.add_argument(
        "--p9-profile",
        action="store_true",
        help=(
            "Use the P9 Report Intelligence corpus profile: add stock, industry, "
            "strategy, macro, fixed-income, and financial-engineering report types "
            "to the private source query set and record P9 coverage targets in the manifest."
        ),
    )
    fetch_reports.add_argument(
        "--max-reports-per-query",
        type=int,
        default=6000,
        help="Local per-query cap after Tushare returns rows. Defaults to 6000.",
    )
    fetch_reports.add_argument(
        "--stock-query-batch-size",
        type=int,
        default=50,
        help="Number of stock codes to join in one Tushare ts_code query. Defaults to 50.",
    )
    fetch_reports.add_argument(
        "--date-chunk-days",
        type=int,
        help=(
            "Days per full-market report_type query window. Defaults to 31, or 7 "
            "when --p9-profile is set."
        ),
    )
    fetch_reports.add_argument(
        "--merge-existing-source",
        action="store_true",
        help=(
            "Merge fetched reports into the existing local research-report source "
            "instead of replacing it."
        ),
    )
    fetch_reports.add_argument(
        "--overwrite-review-templates",
        action="store_true",
        help="Regenerate gold-set and license review templates even when they contain manual values.",
    )
    fetch_reports.add_argument(
        "--env-file",
        help="Optional .env file to load before initializing the Tushare client.",
    )

    report_intelligence = subparsers.add_parser(
        "report-intelligence",
        help=(
            "Materialize Tushare report PDFs, convert with MinerU, and extract "
            "Report Intelligence Loop objects with local vLLM."
        ),
    )
    report_intelligence.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    report_intelligence.add_argument(
        "--env-file",
        help="Optional .env file to load before reading vLLM/OpenAI API keys.",
    )
    report_intelligence.add_argument(
        "--source-path",
        default="registry/sources/tushare_research_reports.jsonl",
        help="Source JSONL path. Defaults to registry/sources/tushare_research_reports.jsonl.",
    )
    report_intelligence.add_argument(
        "--cache-dir",
        default=".mosaic/rke/report_intelligence",
        help="Local PDF/Markdown cache directory. Defaults to .mosaic/rke/report_intelligence.",
    )
    report_intelligence.add_argument(
        "--registry-dir",
        default="registry/report_intelligence",
        help=(
            "Report Intelligence output registry directory. Defaults to "
            "registry/report_intelligence."
        ),
    )
    report_intelligence.add_argument(
        "--source-id",
        action="append",
        dest="source_ids",
        help="Source id to process. May be repeated or comma-separated.",
    )
    report_intelligence.add_argument(
        "--exclude-processed-registry-dir",
        action="append",
        dest="exclude_processed_registry_dirs",
        help=(
            "Registry output directory whose processing_status.jsonl marks "
            "already-processed source ids to skip. May be repeated or comma-separated."
        ),
    )
    report_intelligence.add_argument(
        "--require-cached-markdown",
        action="store_true",
        help=(
            "Only select source rows whose cache-dir markdown file already exists. "
            "Useful for LLM-only incremental batches."
        ),
    )
    report_intelligence.add_argument(
        "--limit",
        type=int,
        help="Maximum selected source rows to process.",
    )
    report_intelligence.add_argument(
        "--min-publish-date",
        help="Only process reports with publish_date >= this YYYY-MM-DD date.",
    )
    report_intelligence.add_argument(
        "--max-publish-date",
        help="Only process reports with publish_date <= this YYYY-MM-DD date.",
    )
    report_intelligence.add_argument(
        "--selection-order",
        choices=("latest", "oldest", "stratified"),
        default="latest",
        help=(
            "Order source selection before applying --limit. Use stratified for "
            "P9 coverage sampling across report type, time, institution, sector, "
            "and stock-code buckets. Defaults to latest."
        ),
    )
    report_intelligence.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-download/re-convert existing local artifacts.",
    )
    report_intelligence.add_argument(
        "--skip-download",
        action="store_true",
        help="Do not download PDFs; use existing local cache only.",
    )
    report_intelligence.add_argument(
        "--skip-convert",
        action="store_true",
        help="Do not run MinerU; use existing Markdown cache only.",
    )
    report_intelligence.add_argument(
        "--skip-llm",
        action="store_true",
        help="Do not call local vLLM; only materialize PDF/Markdown status.",
    )
    report_intelligence.add_argument(
        "--refresh-derived-only",
        action="store_true",
        help=(
            "Recompute derived report-intelligence artifacts from existing "
            "registry extraction outputs without downloading, converting, or "
            "calling local vLLM."
        ),
    )
    report_intelligence.add_argument(
        "--download-timeout-seconds",
        type=int,
        default=60,
        help="PDF download timeout in seconds. Defaults to 60.",
    )
    report_intelligence.add_argument(
        "--mineru-command",
        default="mineru",
        help="MinerU command. Defaults to mineru.",
    )
    report_intelligence.add_argument(
        "--mineru-backend",
        default="hybrid-auto-engine",
        choices=(
            "hybrid-auto-engine",
            "vlm-auto-engine",
            "pipeline",
            "vlm-http-client",
            "hybrid-http-client",
        ),
        help="MinerU backend. Defaults to hybrid-auto-engine.",
    )
    report_intelligence.add_argument(
        "--mineru-server-url",
        help="MinerU VLM/hybrid HTTP backend server URL, passed as -u/--url.",
    )
    report_intelligence.add_argument(
        "--mineru-args-template",
        default="-p {pdf} -o {output_dir} -b {backend} -m auto",
        help=(
            "MinerU args template. Supports {pdf}, {output_dir}, and {backend}. "
            "Defaults to '-p {pdf} -o {output_dir} -b {backend} -m auto'."
        ),
    )
    report_intelligence.add_argument(
        "--mineru-batch-size",
        type=int,
        default=4,
        help="PDF files per MinerU directory batch. Defaults to 4.",
    )
    report_intelligence.add_argument(
        "--mineru-timeout-seconds",
        type=int,
        default=900,
        help="MinerU timeout per batch in seconds. Defaults to 900.",
    )
    report_intelligence.add_argument(
        "--mineru-batch-max-bytes",
        type=int,
        default=5_000_000,
        help=(
            "Maximum total PDF bytes per MinerU batch; <=0 disables byte bucketing. "
            "Defaults to 5000000."
        ),
    )
    report_intelligence.add_argument(
        "--vllm-base-url",
        help=(
            "OpenAI-compatible vLLM base URL. Defaults to "
            "MOSAIC_RKE_VLLM_BASE_URL or http://127.0.0.1:8020/v1."
        ),
    )
    report_intelligence.add_argument(
        "--vllm-model",
        help=(
            "vLLM model id. Defaults to MOSAIC_RKE_VLLM_MODEL; when omitted, "
            "/models first result is used."
        ),
    )
    report_intelligence.add_argument(
        "--vllm-api-key-env",
        default="MOSAIC_VLLM_API_KEY,OPENAI_API_KEY",
        help=(
            "Comma-separated environment variable names for an OpenAI-compatible "
            "chat API key. Defaults to MOSAIC_VLLM_API_KEY,OPENAI_API_KEY."
        ),
    )
    report_intelligence.add_argument(
        "--vllm-timeout-seconds",
        type=int,
        default=DEFAULT_VLLM_TIMEOUT_SECONDS,
        help=(
            "OpenAI-compatible chat request timeout in seconds. "
            f"Defaults to {DEFAULT_VLLM_TIMEOUT_SECONDS}."
        ),
    )
    report_intelligence.add_argument(
        "--max-llm-output-tokens",
        type=int,
        default=4096,
        help="Maximum output tokens per LLM extraction chunk. Defaults to 4096.",
    )
    report_intelligence.add_argument(
        "--qlib-etf-dir",
        default="~/.qlib/qlib_data/cn_etf",
        help="Local qlib ETF data directory for proxy outcome labels.",
    )
    report_intelligence.add_argument(
        "--qlib-stock-dir",
        default="~/.qlib/qlib_data/cn_data",
        help="Local qlib stock data directory for stock proxy outcome labels.",
    )
    report_intelligence.add_argument(
        "--chunk-chars",
        type=int,
        default=60000,
        help="Characters per Markdown chunk sent to vLLM. Defaults to 60000.",
    )
    report_intelligence.add_argument(
        "--max-chunks",
        type=int,
        default=8,
        help="Maximum Markdown chunks per report. Defaults to 8.",
    )
    report_intelligence.add_argument(
        "--progress-jsonl",
        action="store_true",
        help=(
            "Emit redacted progress JSON lines to stderr for long PDF/LLM runs."
        ),
    )

    evolution_gate = subparsers.add_parser(
        "report-intelligence-evolution-gate",
        help=(
            "Rebuild only report-intelligence evolution gate artifacts from "
            "existing registry evidence."
        ),
    )
    evolution_gate.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    evolution_gate.add_argument(
        "--run-id",
        default="RIR-PUBLIC-EVOLUTION-GATE",
        help="Run id to stamp on the rebuilt evolution gate.",
    )
    evolution_gate.add_argument(
        "--refresh-prompt-mutations",
        action="store_true",
        help="Also rebuild prompt mutation candidates after writing the gate.",
    )
    evolution_readiness = subparsers.add_parser(
        "evolution-readiness",
        help=(
            "Alias for report-intelligence-evolution-gate; rebuild evolution "
            "readiness gate artifacts from existing registry evidence."
        ),
    )
    evolution_readiness.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    evolution_readiness.add_argument(
        "--run-id",
        default="RIR-PUBLIC-EVOLUTION-GATE",
        help="Run id to stamp on the rebuilt evolution gate.",
    )
    evolution_readiness.add_argument(
        "--refresh-prompt-mutations",
        action="store_true",
        help="Also rebuild prompt mutation candidates after writing the gate.",
    )
    merge_report_batches = subparsers.add_parser(
        "merge-report-intelligence-batches",
        help=(
            "Merge multiple local report-intelligence batch output directories "
            "into the registry JSONL inputs."
        ),
    )
    merge_report_batches.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    merge_report_batches.add_argument(
        "--input-dir",
        action="append",
        required=True,
        help=(
            "Batch output directory containing report-intelligence JSONL files. "
            "May be repeated."
        ),
    )
    merge_report_batches.add_argument(
        "--refresh-derived",
        action="store_true",
        help="After merging rows, recompute public derived report-intelligence artifacts.",
    )
    merge_report_batches.add_argument(
        "--replace",
        action="store_true",
        help=(
            "Replace registry JSONL inputs from the supplied batches instead of "
            "preserving existing registry rows first."
        ),
    )

    apply_footprint_review = subparsers.add_parser(
        "apply-footprint-review",
        help="Validate and apply an analytical-footprint manual review JSONL import.",
    )
    apply_footprint_review.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    apply_footprint_review.add_argument(
        "--input",
        required=True,
        help="JSONL file containing analytical-footprint review decisions.",
    )
    apply_footprint_review.add_argument(
        "--dry-run", action="store_true", help="Validate without mutating the registry."
    )

    prepare_footprint_review = subparsers.add_parser(
        "prepare-footprint-review",
        help="Prepare a gitignored analytical-footprint review import scaffold.",
    )
    prepare_footprint_review.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    prepare_footprint_review.add_argument(
        "--output",
        help=(
            "Output JSONL import scaffold. Defaults to the full reviewed path, "
            "or the batch reviewed path when --limit is set."
        ),
    )
    prepare_footprint_review.add_argument(
        "--reviewer",
        default="",
        help="Optional reviewer name to prefill in each scaffold row.",
    )
    prepare_footprint_review.add_argument(
        "--review-date",
        default="",
        help="Optional YYYY-MM-DD review date to prefill in each scaffold row.",
    )
    prepare_footprint_review.add_argument(
        "--limit",
        type=int,
        help="Maximum rows to scaffold. Omit for all rows.",
    )
    prepare_footprint_review.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Review-row offset before applying --limit. Defaults to 0.",
    )
    prepare_footprint_review.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing output scaffold.",
    )

    write_footprint_review_assist = subparsers.add_parser(
        "write-footprint-review-assist",
        help="Write private analytical-footprint review assist JSONL and workbook files.",
    )
    write_footprint_review_assist.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    write_footprint_review_evidence = subparsers.add_parser(
        "write-footprint-review-evidence",
        help=(
            "Write private analytical-footprint evidence snippets and draft "
            "review suggestions."
        ),
    )
    write_footprint_review_evidence.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    write_footprint_review_evidence.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Maximum pending rows to include. Defaults to 25.",
    )
    write_footprint_review_evidence.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Pending-row offset after priority sorting. Use with --limit for review batches.",
    )
    write_footprint_review_evidence.add_argument(
        "--review-input",
        help=(
            "Optional reviewed JSONL scratch file. When set, evidence rows follow "
            "this input order and are matched back to the full footprint review template."
        ),
    )

    validate = subparsers.add_parser(
        "validate-required", help="Validate required registry files."
    )
    validate.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root)

    if args.command == "refresh":
        result = run_full_rke_refresh(
            root,
            preserve_review_templates=not args.overwrite_review_templates,
        )
        _print_json(asdict(result))
        return 0 if result.manifest_valid else 2
    if args.command == "manifest":
        result = write_registry_manifest(root)
        _print_json(result)
        return 0 if result["valid"] else 2
    if args.command == "audit":
        result = write_completion_audit(root)
        _print_json(result)
        return 0
    if args.command == "audit-view":
        paths = write_audit_trace_view(root)
        view = build_audit_trace_view(root)
        _print_json(
            {
                "paths": paths,
                "complete": view.complete,
                "node_count": view.node_count,
                "edge_count": view.edge_count,
                "missing_references": view.missing_references,
                "broken_edges": view.broken_edges,
            }
        )
        return 0 if view.complete else 2
    if args.command == "master-plan-status":
        write_audit_trace_view(root)
        write_completion_audit(root)
        write_master_plan_coverage_report(root)
        result = build_master_plan_coverage_report(root)
        _print_json(asdict(result))
        return 0 if result.coverage_complete else 2
    if args.command == "dashboard":
        result = write_dashboard_reports(root)
        _print_json(result)
        return 0
    if args.command == "policy-doc-status":
        write_policy_doc_validation_report(root)
        result = build_policy_doc_validation_report(root)
        _print_json(asdict(result))
        return 0 if result.accepted else 2
    if args.command == "schema-status":
        if not args.no_write:
            write_schema_validation_report(root)
            write_rule_pack_validation_report(root)
        result = build_schema_validation_report(root)
        records = list(result.records)
        if args.failures_only:
            records = [
                record
                for record in records
                if not record.accepted or record.failures
            ]
        _print_json(
            {
                "accepted": result.accepted,
                "failure_count": result.failure_count,
                "record_count": len(result.records),
                "reported_record_count": len(records),
                "records": [asdict(record) for record in records],
            }
        )
        return 0 if result.accepted else 2
    if args.command == "rule-pack-status":
        write_rule_pack_validation_report(root)
        result = build_rule_pack_validation_report(root)
        _print_json(
            {
                "accepted": result.accepted,
                "failure_count": result.failure_count,
                "records": [asdict(record) for record in result.records],
            }
        )
        return 0 if result.accepted else 2
    if args.command == "prompt-status":
        write_prompt_asset_validation_report(root)
        result = build_prompt_asset_validation_report(root)
        _print_json(
            {
                "accepted": result.accepted,
                "failure_count": result.failure_count,
                "records": [asdict(record) for record in result.records],
            }
        )
        return 0 if result.accepted else 2
    if args.command == "claim-status":
        write_claim_grounding_validation_report(root)
        write_claim_variable_validation_report(root)
        result = build_claim_variable_validation_report(root)
        _print_json(
            {
                "accepted": result.accepted,
                "failure_count": result.failure_count,
                "records": [asdict(record) for record in result.records],
            }
        )
        return 0 if result.accepted else 2
    if args.command == "source-status":
        write_source_registry_validation_report(root)
        result = build_source_registry_validation_report(root)
        _print_json(asdict(result))
        return 0 if result.accepted_for_sandbox else 2
    if args.command == "source-text-status":
        write_source_text_redaction_report(root)
        result = build_source_text_redaction_report(root)
        _print_json(asdict(result))
        return 0 if result.accepted else 2
    if args.command == "validation-status":
        write_validation_hardening_report(root)
        write_statistical_significance_report(root)
        write_experiment_validation_report(root)
        hardening = build_central_bank_validation_hardening_report()
        significance = build_central_bank_statistical_significance_report()
        experiment_validation = build_experiment_validation_report(root)
        accepted = (
            not hardening["horizon_metric_failures"]
            and not hardening["precision_failures"]
            and hardening["ablation_checks"]["accepted"] is True
            and significance.accepted
            and experiment_validation.accepted
        )
        _print_json(
            {
                "accepted": accepted,
                "experiment_id": significance.experiment_id,
                "experiment_validation": {
                    "accepted": experiment_validation.accepted,
                    "failure_count": experiment_validation.failure_count,
                    "records": [
                        asdict(record) for record in experiment_validation.records
                    ],
                },
                "statistical_significance": asdict(significance),
                "validation_hardening": hardening,
            }
        )
        return 0 if accepted else 2
    if args.command == "experiment-status":
        write_experiment_validation_report(root)
        result = build_experiment_validation_report(root)
        _print_json(
            {
                "accepted": result.accepted,
                "failure_count": result.failure_count,
                "records": [asdict(record) for record in result.records],
            }
        )
        return 0 if result.accepted else 2
    if args.command == "monitoring-diagnostics":
        write_production_monitor_diagnostics(root)
        result = build_production_monitor_diagnostics()
        _print_json(asdict(result))
        return 0 if result.accepted else 2
    if args.command == "rollback-readiness":
        result = write_rollback_readiness_report(root)
        report = build_rollback_readiness_report(root)
        _print_json({"path": result["path"], **asdict(report)})
        return 0 if report.accepted else 2
    if args.command == "promotion-status":
        write_production_promotion_gate_report(root)
        result = build_production_promotion_gate_report(root)
        _print_json(asdict(result))
        return 0 if result.paper_trading_allowed else 2
    if args.command == "promotion-dry-run":
        if args.write_report:
            write_promotion_dry_run_report(
                root,
                gold_input=args.gold_input,
                footprint_input=args.footprint_input,
                license_input=args.license_input,
                lockbox_input=args.lockbox_input,
            )
        result = build_promotion_dry_run_report(
            root,
            gold_input=args.gold_input,
            footprint_input=args.footprint_input,
            license_input=args.license_input,
            lockbox_input=args.lockbox_input,
        )
        _print_json(asdict(result))
        return 0 if result.accepted else 2
    if args.command == "gold-set-status":
        write_gold_set_review_summary(root)
        _print_json(asdict(summarize_gold_set_review(root)))
        return 0
    if args.command == "gold-review-packet":
        paths = write_gold_review_packet(root)
        packet = build_gold_review_packet(root)
        _print_json(
            {
                "paths": paths,
                "packet_id": packet.packet_id,
                "status": packet.status,
                "document_count": packet.document_count,
                "review_row_count": packet.review_row_count,
                "pending_review_rows": packet.pending_review_rows,
                "candidate_claim_count": packet.candidate_claim_count,
                "candidate_claim_available_count": packet.candidate_claim_available_count,
                "review_rows_with_candidate_fields": packet.review_rows_with_candidate_fields,
                "candidate_span_ref_count": packet.candidate_span_ref_count,
                "domain_counts": packet.domain_counts,
                "manual_review_required": packet.manual_review_required,
                "risk_flag_counts": packet.risk_flag_counts,
            }
        )
        return 0
    if args.command == "gold-candidate-claims":
        paths = write_gold_candidate_claims(root)
        summary = json.loads(Path(paths["summary"]).read_text(encoding="utf-8"))
        _print_json(
            {
                "paths": paths,
                "summary_id": summary["summary_id"],
                "candidate_claim_count": summary["candidate_claim_count"],
                "candidate_available_count": summary["candidate_available_count"],
                "missing_variable_mapping_count": summary[
                    "missing_variable_mapping_count"
                ],
                "review_rows_with_candidate_fields": summary[
                    "review_rows_with_candidate_fields"
                ],
                "manual_fields_preserved": summary["manual_fields_preserved"],
                "direction_counts": summary["direction_counts"],
                "claim_type_counts": summary["claim_type_counts"],
                "blockers": summary.get("blockers", []),
            }
        )
        return 0
    if args.command == "license-status":
        write_source_license_review_summary(root)
        _print_json(
            _source_license_status_stdout(summarize_source_license_review(root))
        )
        return 0
    if args.command == "license-review-packet":
        paths = write_license_review_packet(root)
        packet = build_license_review_packet(root)
        _print_json(
            {
                "paths": paths,
                "packet_id": packet.packet_id,
                "status": packet.status,
                "source_count": packet.source_count,
                "review_row_count": packet.review_row_count,
                "pending_sources": packet.pending_sources,
                "approved_for_derived_claim_storage": packet.approved_for_derived_claim_storage,
                "approved_for_production_runtime": packet.approved_for_production_runtime,
                "manual_review_required": packet.manual_review_required,
                "policy_reason_counts": packet.policy_reason_counts,
            }
        )
        return 0
    if args.command == "apply-gold-review":
        report = apply_gold_set_review_import(root, args.input, dry_run=args.dry_run)
        _print_json(asdict(report))
        return 0 if report.accepted else 2
    if args.command == "prepare-gold-review":
        result = write_gold_review_starter(
            root,
            output_path=args.output,
            full=args.full,
            force=args.force,
            gold_batch_size=args.gold_batch_size,
            offset=args.offset,
            reviewer=args.reviewer,
            review_date=args.review_date,
        )
        _print_json(asdict(result))
        return 0 if result.written else 2
    if args.command == "write-gold-review-evidence":
        result = write_gold_review_evidence(
            root,
            limit=args.limit,
            offset=args.offset,
            review_input_path=args.review_input,
        )
        _print_json(result)
        return 0 if result["blockers"] == 0 else 2
    if args.command == "apply-license-review":
        report = apply_source_license_review_import(
            root, args.input, dry_run=args.dry_run
        )
        _print_json(asdict(report))
        return 0 if report.accepted else 2
    if args.command == "build-license-review-import":
        report = build_source_license_policy_import(
            root,
            args.policy,
            output_path=args.output,
            dry_run=args.dry_run,
        )
        _print_json(asdict(report))
        return 0 if report.accepted else 2
    if args.command == "prepare-license-policy-review":
        result = write_source_license_reviewed_policy_starter(
            root,
            output_path=args.output,
            force=args.force,
        )
        _print_json(asdict(result))
        return 0 if result.written else 2
    if args.command == "apply-lockbox-review":
        upstream_blockers = (
            ()
            if args.allow_pending_upstream
            else lockbox_upstream_review_blockers(root)
        )
        if upstream_blockers:
            _print_json(
                {
                    "accepted": False,
                    "applied": False,
                    "allow_pending_upstream": False,
                    "rejected_reasons": list(upstream_blockers),
                    "upstream_blockers": list(upstream_blockers),
                }
            )
            return 2
        report = apply_lockbox_review_import(root, args.input, dry_run=args.dry_run)
        _print_json(asdict(report))
        return 0 if report.accepted else 2
    if args.command == "prepare-lockbox-review":
        result = write_lockbox_review_starter(
            root,
            output_path=args.output,
            force=args.force,
            allow_pending_upstream=args.allow_pending_upstream,
        )
        _print_json(asdict(result))
        return 0 if result.written else 2
    if args.command == "review-batches":
        paths = write_manual_review_batches(
            root,
            gold_batch_size=args.gold_batch_size,
            license_batch_size=args.license_batch_size,
        )
        status, _, _ = build_manual_review_batch_status(
            root,
            gold_batch_size=args.gold_batch_size,
            license_batch_size=args.license_batch_size,
        )
        _print_json({"paths": paths, "status": asdict(status)})
        return 0 if status.ready_for_manual_review else 2
    if args.command == "operator-handoff":
        paths = write_operator_handoff(root)
        handoff = build_operator_handoff(root)
        _print_json({"paths": paths, "handoff": asdict(handoff)})
        return 0 if handoff.ready_for_operator_review else 2
    if args.command == "operator-readiness":
        result = write_operator_readiness_report(root)
        report = build_operator_readiness_report(root)
        _print_json({"path": result["path"], **asdict(report)})
        return 0 if report.accepted else 2
    if args.command == "review-progress":
        if args.review_kind and not args.summary:
            _print_json(
                {
                    "accepted": False,
                    "blockers": ["--review-kind requires --summary"],
                }
            )
            return 2
        report = build_manual_review_progress(root)
        if args.no_write:
            result = {"path": str(root / "registry/review_batches/manual_review_progress_report.json")}
            runbook = {"path": str(root / "registry/review_batches/manual_review_runbook.md")}
        else:
            result = write_manual_review_progress_report(root)
            runbook = write_manual_review_runbook(root)
        if args.summary:
            summary = build_manual_review_progress_summary(
                report,
                path=result["path"],
                runbook_path=runbook["path"],
                review_kinds=tuple(args.review_kind or ()),
            )
            _print_json(summary)
            return 0 if bool(summary["ready_for_promotion_dry_run"]) else 2
        else:
            _print_json(
                {
                    "path": result["path"],
                    "runbook_path": runbook["path"],
                    **asdict(report),
                }
            )
        return 0 if report.ready_for_promotion_dry_run else 2
    if args.command == "fetch-tushare-reports":
        _load_env_file(args.env_file)
        date_chunk_days = args.date_chunk_days
        if date_chunk_days is None:
            date_chunk_days = 7 if args.p9_profile else 31
        result = refresh_tushare_research_report_registry(
            root,
            stock_codes=_split_repeated_csv(args.stock_codes),
            industry_keywords=_split_repeated_csv(args.industry_keywords),
            report_types=_split_repeated_csv(args.report_types),
            start_date=args.start_date,
            end_date=args.end_date,
            input_path=args.input_path,
            max_reports_per_query=args.max_reports_per_query,
            stock_query_batch_size=args.stock_query_batch_size,
            date_chunk_days=date_chunk_days,
            merge_existing_source=args.merge_existing_source,
            preserve_review_templates=not args.overwrite_review_templates,
            corpus_profile=(
                P9_REPORT_INTELLIGENCE_CORPUS_PROFILE if args.p9_profile else None
            ),
        )
        _print_json(asdict(result))
        return 0 if result.manifest_valid else 2
    if args.command == "report-intelligence":
        _load_env_file(args.env_file)
        result = run_report_intelligence_refresh(
            ReportIntelligenceConfig(
                root=root,
                source_path=args.source_path,
                registry_dir=args.registry_dir,
                cache_dir=args.cache_dir,
                source_ids=_split_repeated_csv(args.source_ids),
                exclude_processed_registry_dirs=_split_repeated_csv(
                    args.exclude_processed_registry_dirs
                ),
                require_cached_markdown=args.require_cached_markdown,
                limit=args.limit,
                min_publish_date=args.min_publish_date,
                max_publish_date=args.max_publish_date,
                selection_order=args.selection_order,
                overwrite=args.overwrite,
                skip_download=args.skip_download,
                skip_convert=args.skip_convert,
                skip_llm=args.skip_llm,
                refresh_derived_only=args.refresh_derived_only,
                download_timeout_seconds=args.download_timeout_seconds,
                mineru_command=args.mineru_command,
                mineru_backend=args.mineru_backend,
                mineru_server_url=args.mineru_server_url,
                mineru_args_template=args.mineru_args_template,
                mineru_timeout_seconds=args.mineru_timeout_seconds,
                mineru_batch_size=args.mineru_batch_size,
                mineru_batch_max_bytes=args.mineru_batch_max_bytes,
                vllm_base_url=args.vllm_base_url
                or os.environ.get("MOSAIC_RKE_VLLM_BASE_URL")
                or "http://127.0.0.1:8020/v1",
                vllm_model=args.vllm_model
                or os.environ.get("MOSAIC_RKE_VLLM_MODEL"),
                vllm_api_key=next(
                    (
                        os.environ[name.strip()]
                        for name in str(args.vllm_api_key_env or "").split(",")
                        if name.strip() and os.environ.get(name.strip())
                    ),
                    None,
                ),
                qlib_etf_dir=args.qlib_etf_dir,
                qlib_stock_dir=args.qlib_stock_dir,
                vllm_timeout_seconds=args.vllm_timeout_seconds,
                chunk_chars=args.chunk_chars,
                max_chunks=args.max_chunks,
                max_llm_output_tokens=args.max_llm_output_tokens,
                progress_jsonl=args.progress_jsonl,
            )
        )
        _print_json(asdict(result))
        return 0 if result.blocker_count == 0 else 2
    if args.command in {"report-intelligence-evolution-gate", "evolution-readiness"}:
        registry_dir = root / "registry/report_intelligence"
        result = write_report_intelligence_evolution_readiness_gate(
            registry_dir,
            run_id=args.run_id,
        )
        if args.refresh_prompt_mutations:
            result = {
                **result,
                **write_report_intelligence_prompt_mutation_candidates(
                    registry_dir,
                    run_id=args.run_id,
                ),
            }
        _print_json(result)
        return 0 if not result.get("input_load_blockers") else 2
    if args.command == "merge-report-intelligence-batches":
        result = merge_report_intelligence_batch_outputs(
            root=root,
            input_dirs=args.input_dir,
            include_existing_registry=not args.replace,
        )
        if args.refresh_derived and result["blocker_count"] == 0:
            refresh = run_report_intelligence_refresh(
                ReportIntelligenceConfig(root=root, refresh_derived_only=True)
            )
            result = {**result, "derived_refresh": asdict(refresh)}
        _print_json(result)
        return 0 if result["blocker_count"] == 0 else 2
    if args.command == "apply-footprint-review":
        report = apply_analytical_footprint_review_import(
            root,
            args.input,
            dry_run=args.dry_run,
        )
        _print_json(asdict(report))
        return 0 if report.accepted else 2
    if args.command == "prepare-footprint-review":
        if args.output:
            footprint_output = args.output
        elif args.limit is not None:
            footprint_output = ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH
        else:
            footprint_output = ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH
        report = prepare_analytical_footprint_review_import(
            root,
            footprint_output,
            reviewer=args.reviewer,
            review_date=args.review_date,
            limit=args.limit,
            offset=args.offset,
            overwrite=args.overwrite,
        )
        _print_json(asdict(report))
        return 0 if report.accepted else 2
    if args.command == "write-footprint-review-assist":
        report = write_analytical_footprint_review_assist(root)
        _print_json(asdict(report))
        return 0 if not report.blockers else 2
    if args.command == "write-footprint-review-evidence":
        report = write_analytical_footprint_review_evidence(
            root,
            limit=args.limit,
            offset=args.offset,
            review_input_path=args.review_input,
        )
        _print_json(asdict(report))
        return 0 if not report.blockers else 2
    if args.command == "validate-required":
        missing, empty = validate_required_registry(root)
        invalid = validate_required_registry_content(root)
        manifest = build_registry_manifest(root) if not missing and not empty else None
        valid = not missing and not empty and not invalid
        _print_json(
            {
                "valid": valid,
                "missing_required": missing,
                "empty_required": empty,
                "invalid_required": invalid,
                "artifact_count": manifest.artifact_count if manifest else None,
            }
        )
        return 0 if valid else 2
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
