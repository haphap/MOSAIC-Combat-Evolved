"""Command-line entry points for RKE registry operations."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Sequence

from .audit_viewer import build_audit_trace_view, write_audit_trace_view
from .claim_vocabulary import (
    build_claim_variable_validation_report,
    write_claim_variable_validation_report,
    write_claim_variable_vocabulary,
)
from .completion_auditor import write_completion_audit
from .dashboard_reports import write_dashboard_reports
from .gold_candidate_claims import (
    write_gold_candidate_claims,
)
from .gold_review_packet import build_gold_review_packet, write_gold_review_packet
from .license_review_packet import build_license_review_packet, write_license_review_packet
from .license_policy_import import build_source_license_policy_import
from .lockbox_review_import import apply_lockbox_review_import
from .manual_review_import import (
    apply_gold_set_review_import,
    apply_source_license_review_import,
)
from .manual_review_batches import (
    build_manual_review_batch_status,
    write_manual_review_batches,
)
from .master_plan_coverage import (
    build_master_plan_coverage_report,
    write_master_plan_coverage_report,
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
from .registry_manifest import (
    build_registry_manifest,
    validate_required_registry,
    write_registry_manifest,
)
from .review_gates import (
    summarize_gold_set_review,
    summarize_source_license_review,
    write_gold_set_review_summary,
    write_source_license_review_summary,
)
from .schema_validation import build_schema_validation_report, write_schema_validation_report
from .source_registry_validation import (
    build_source_registry_validation_report,
    write_source_registry_validation_report,
)
from .source_text_redaction import (
    build_source_text_redaction_report,
    write_source_text_redaction_report,
)
from .tushare_reports import refresh_tushare_research_report_registry
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

    refresh = subparsers.add_parser("refresh", help="Regenerate local RKE registry artifacts.")
    refresh.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
    refresh.add_argument(
        "--overwrite-review-templates",
        action="store_true",
        help="Regenerate gold-set and license review templates even when they exist.",
    )

    manifest = subparsers.add_parser("manifest", help="Write the registry manifest.")
    manifest.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

    audit = subparsers.add_parser("audit", help="Recompute completion audit.")
    audit.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

    audit_view = subparsers.add_parser(
        "audit-view",
        help="Write and print the central-bank source-to-output audit trace viewer.",
    )
    audit_view.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

    master_plan_status = subparsers.add_parser(
        "master-plan-status",
        help="Write and print the master-plan coverage audit.",
    )
    master_plan_status.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

    dashboard = subparsers.add_parser("dashboard", help="Write dashboard JSON and Markdown reports.")
    dashboard.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

    policy_doc_status = subparsers.add_parser(
        "policy-doc-status",
        help="Write and print the RKE policy documentation validation report.",
    )
    policy_doc_status.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

    schema_status = subparsers.add_parser(
        "schema-status",
        help="Write and print the Phase 1 schema validation report.",
    )
    schema_status.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

    prompt_status = subparsers.add_parser(
        "prompt-status",
        help="Write and print the rendered prompt asset validation report.",
    )
    prompt_status.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

    claim_status = subparsers.add_parser(
        "claim-status",
        help="Write and print the claim variable vocabulary validation report.",
    )
    claim_status.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

    source_status = subparsers.add_parser(
        "source-status",
        help="Write and print the source registry validation report.",
    )
    source_status.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

    source_text_status = subparsers.add_parser(
        "source-text-status",
        help="Write and print the Tushare source-text redaction audit report.",
    )
    source_text_status.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

    validation_status = subparsers.add_parser(
        "validation-status",
        help="Write and print the validation-hardening and statistical-significance reports.",
    )
    validation_status.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

    promotion_status = subparsers.add_parser(
        "promotion-status",
        help="Write and print the production-promotion gate report.",
    )
    promotion_status.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

    gold_status = subparsers.add_parser(
        "gold-set-status",
        help="Write and print the manual gold-set review gate summary.",
    )
    gold_status.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

    gold_packet = subparsers.add_parser(
        "gold-review-packet",
        help="Write and print the Phase -1 gold-set manual review packet summary.",
    )
    gold_packet.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

    gold_candidate_claims = subparsers.add_parser(
        "gold-candidate-claims",
        help="Write and print deterministic source-bound candidate claims for gold-set review.",
    )
    gold_candidate_claims.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

    license_status = subparsers.add_parser(
        "license-status",
        help="Write and print the source license review gate summary.",
    )
    license_status.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

    license_packet = subparsers.add_parser(
        "license-review-packet",
        help="Write and print the source license manual review packet summary.",
    )
    license_packet.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

    apply_gold_review = subparsers.add_parser(
        "apply-gold-review",
        help="Validate and apply a JSONL manual gold-set review import.",
    )
    apply_gold_review.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
    apply_gold_review.add_argument("--input", required=True, help="JSONL file containing reviewed gold-set rows.")
    apply_gold_review.add_argument("--dry-run", action="store_true", help="Validate without changing review rows.")

    apply_license_review = subparsers.add_parser(
        "apply-license-review",
        help="Validate and apply a JSONL source-license review import.",
    )
    apply_license_review.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
    apply_license_review.add_argument("--input", required=True, help="JSONL file containing source license decisions.")
    apply_license_review.add_argument("--dry-run", action="store_true", help="Validate without changing review rows.")

    build_license_import = subparsers.add_parser(
        "build-license-review-import",
        help="Expand a signed source-license policy JSON into an apply-license-review JSONL input.",
    )
    build_license_import.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
    build_license_import.add_argument("--policy", required=True, help="JSON policy file with reviewer/date, decisions, and filters.")
    build_license_import.add_argument(
        "--output",
        default="registry/review_batches/source_license_policy_import.jsonl",
        help="Output JSONL path. Defaults to registry/review_batches/source_license_policy_import.jsonl.",
    )
    build_license_import.add_argument("--dry-run", action="store_true", help="Validate and report without writing output JSONL.")

    apply_lockbox_review = subparsers.add_parser(
        "apply-lockbox-review",
        help="Validate and apply a JSON lockbox review record.",
    )
    apply_lockbox_review.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
    apply_lockbox_review.add_argument("--input", required=True, help="JSON file containing one lockbox review record.")
    apply_lockbox_review.add_argument("--dry-run", action="store_true", help="Validate without changing the lockbox record.")

    review_batches = subparsers.add_parser(
        "review-batches",
        help="Write next-batch import templates for manual gold-set and source-license reviews.",
    )
    review_batches.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
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

    fetch_reports = subparsers.add_parser(
        "fetch-tushare-reports",
        help="Fetch Tushare research reports and refresh dependent Phase -1 registry artifacts.",
    )
    fetch_reports.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
    fetch_reports.add_argument("--start-date", required=True, help="Inclusive YYYY-MM-DD query start date.")
    fetch_reports.add_argument("--end-date", required=True, help="Inclusive YYYY-MM-DD query end date.")
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
        default=31,
        help="Days per full-market report_type query window. Defaults to 31.",
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

    validate = subparsers.add_parser("validate-required", help="Validate required registry files.")
    validate.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
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
        write_schema_validation_report(root)
        result = build_schema_validation_report(root)
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
        write_claim_variable_vocabulary(root)
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
        hardening = build_central_bank_validation_hardening_report()
        significance = build_central_bank_statistical_significance_report()
        accepted = (
            not hardening["horizon_metric_failures"]
            and not hardening["precision_failures"]
            and hardening["ablation_checks"]["accepted"] is True
            and significance.accepted
        )
        _print_json(
            {
                "accepted": accepted,
                "experiment_id": significance.experiment_id,
                "statistical_significance": asdict(significance),
                "validation_hardening": hardening,
            }
        )
        return 0 if accepted else 2
    if args.command == "promotion-status":
        write_production_promotion_gate_report(root)
        result = build_production_promotion_gate_report(root)
        _print_json(asdict(result))
        return 0 if result.paper_trading_allowed else 2
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
                "missing_variable_mapping_count": summary["missing_variable_mapping_count"],
                "review_rows_with_candidate_fields": summary["review_rows_with_candidate_fields"],
                "manual_fields_preserved": summary["manual_fields_preserved"],
                "direction_counts": summary["direction_counts"],
                "claim_type_counts": summary["claim_type_counts"],
            }
        )
        return 0
    if args.command == "license-status":
        write_source_license_review_summary(root)
        _print_json(asdict(summarize_source_license_review(root)))
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
    if args.command == "apply-license-review":
        report = apply_source_license_review_import(root, args.input, dry_run=args.dry_run)
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
    if args.command == "apply-lockbox-review":
        report = apply_lockbox_review_import(root, args.input, dry_run=args.dry_run)
        _print_json(asdict(report))
        return 0 if report.accepted else 2
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
    if args.command == "fetch-tushare-reports":
        _load_env_file(args.env_file)
        result = refresh_tushare_research_report_registry(
            root,
            stock_codes=_split_repeated_csv(args.stock_codes),
            industry_keywords=_split_repeated_csv(args.industry_keywords),
            report_types=_split_repeated_csv(args.report_types),
            start_date=args.start_date,
            end_date=args.end_date,
            max_reports_per_query=args.max_reports_per_query,
            stock_query_batch_size=args.stock_query_batch_size,
            date_chunk_days=args.date_chunk_days,
            preserve_review_templates=not args.overwrite_review_templates,
        )
        _print_json(asdict(result))
        return 0 if result.manifest_valid else 2
    if args.command == "validate-required":
        missing, empty = validate_required_registry(root)
        manifest = build_registry_manifest(root) if not missing and not empty else None
        _print_json(
            {
                "valid": not missing and not empty,
                "missing_required": missing,
                "empty_required": empty,
                "artifact_count": manifest.artifact_count if manifest else None,
            }
        )
        return 0 if not missing and not empty else 2
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
