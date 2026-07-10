#!/usr/bin/env python3
"""Run or verify the prompt-evolution delivery evidence contract."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from mosaic.rke.prompt_evolution_delivery import (
    generate_delivery_status,
    validate_delivery_status,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default=".mosaic/prompt_evolution_delivery/status.json")
    parser.add_argument("--verify")
    parser.add_argument("--allow-blocked", action="store_true")
    parser.add_argument(
        "--ci-provider",
        default="github_actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local",
    )
    parser.add_argument("--ci-run-id", default=os.environ.get("GITHUB_RUN_ID", "local"))
    parser.add_argument("--ci-run-url", default=os.environ.get("PROMPT_EVOLUTION_CI_RUN_URL", ""))
    parser.add_argument("--ci-head-sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument(
        "--python-ci-status",
        default=os.environ.get("PROMPT_EVOLUTION_PYTHON_CI_STATUS", "blocked"),
    )
    parser.add_argument(
        "--typescript-ci-status",
        default=os.environ.get("PROMPT_EVOLUTION_TYPESCRIPT_CI_STATUS", "blocked"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    if args.verify:
        artifact = json.loads(Path(args.verify).read_text(encoding="utf-8"))
        reasons = validate_delivery_status(root, artifact)
        if reasons:
            print(json.dumps({"valid": False, "reasons": reasons}, indent=2))
            return 1
        print(json.dumps({"valid": True, "status": artifact["summary"]["overall_status"]}))
        return 0 if artifact["summary"]["ready"] or args.allow_blocked else 1

    run_id = str(args.ci_run_id or "local").replace("/", "-")
    artifact = generate_delivery_status(
        root,
        output=Path(args.output),
        run_id=run_id,
        ci_provider=args.ci_provider,
        ci_run_id=str(args.ci_run_id),
        ci_run_url=str(args.ci_run_url),
        ci_head_sha=str(args.ci_head_sha),
        python_ci_status=str(args.python_ci_status),
        typescript_ci_status=str(args.typescript_ci_status),
    )
    print(
        json.dumps(
            {
                "output": str(Path(args.output)),
                "overall_status": artifact["summary"]["overall_status"],
                "ready": artifact["summary"]["ready"],
                "manifest_hash": artifact["manifest_hash"],
            },
            indent=2,
        )
    )
    if artifact["summary"]["ready"]:
        return 0
    return 0 if args.allow_blocked and artifact["summary"]["overall_status"] == "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
