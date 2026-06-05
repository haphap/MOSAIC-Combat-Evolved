"""Command-line entry points for RKE registry operations."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Sequence

from .claim_vocabulary import (
    build_claim_variable_validation_report,
    write_claim_variable_validation_report,
    write_claim_variable_vocabulary,
)
from .completion_auditor import write_completion_audit
from .dashboard_reports import write_dashboard_reports
from .prompt_asset_validation import (
    build_prompt_asset_validation_report,
    write_prompt_asset_validation_report,
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

    dashboard = subparsers.add_parser("dashboard", help="Write dashboard JSON and Markdown reports.")
    dashboard.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

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

    validation_status = subparsers.add_parser(
        "validation-status",
        help="Write and print the validation-hardening and statistical-significance reports.",
    )
    validation_status.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

    gold_status = subparsers.add_parser(
        "gold-set-status",
        help="Write and print the manual gold-set review gate summary.",
    )
    gold_status.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

    license_status = subparsers.add_parser(
        "license-status",
        help="Write and print the source license review gate summary.",
    )
    license_status.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")

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
        "--max-reports-per-query",
        type=int,
        default=6000,
        help="Local per-query cap after Tushare returns rows. Defaults to 6000.",
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
    if args.command == "dashboard":
        result = write_dashboard_reports(root)
        _print_json(result)
        return 0
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
    if args.command == "gold-set-status":
        write_gold_set_review_summary(root)
        _print_json(asdict(summarize_gold_set_review(root)))
        return 0
    if args.command == "license-status":
        write_source_license_review_summary(root)
        _print_json(asdict(summarize_source_license_review(root)))
        return 0
    if args.command == "fetch-tushare-reports":
        _load_env_file(args.env_file)
        result = refresh_tushare_research_report_registry(
            root,
            stock_codes=_split_repeated_csv(args.stock_codes),
            industry_keywords=_split_repeated_csv(args.industry_keywords),
            start_date=args.start_date,
            end_date=args.end_date,
            max_reports_per_query=args.max_reports_per_query,
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
