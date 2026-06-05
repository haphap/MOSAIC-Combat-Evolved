"""Command-line entry points for RKE registry operations."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

from .completion_auditor import write_completion_audit
from .dashboard_reports import write_dashboard_reports
from .registry_manifest import (
    build_registry_manifest,
    validate_required_registry,
    write_registry_manifest,
)
from .workflows import run_full_rke_refresh


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


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
