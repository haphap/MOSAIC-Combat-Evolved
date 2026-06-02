"""Operator-run baseline drift check for private prompt overrides.

This script intentionally does not run in project CI: CI usually has neither
the private prompt repo nor the production scorecard DB. Operators run it before
release or after baseline prompt changes to find private overrides that would
shadow the new public baseline.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


PROMPT_RE = re.compile(
    r"^prompts/mosaic/(?P<cohort>[^/]+)/(?P<layer>[^/]+)/(?P<agent>[^/.]+)\.(?P<lang>zh|en)\.md$"
)


_SYNC_MANIFEST = "prompts/mosaic/.baseline-sync.json"


@dataclass(frozen=True)
class DriftFinding:
    path: str
    cohort: str
    layer: str
    agent: str
    lang: str
    baseline_ref: str
    private_ref: str
    private_path: str
    baseline_blob_sha: str


@dataclass(frozen=True)
class DriftState:
    baseline_ref: str


def _run_git(repo: Path, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout


def _repo_root(path: Path) -> Path:
    out = _run_git(path, ["rev-parse", "--show-toplevel"])
    return Path(out.strip()).resolve()


def _changed_prompt_paths(repo: Path, base_ref: str) -> list[str]:
    out = _run_git(
        repo,
        ["diff", "--name-only", "--diff-filter=ACMRT", f"{base_ref}...HEAD", "--", "prompts/mosaic"],
    )
    return sorted({line.strip() for line in out.splitlines() if PROMPT_RE.match(line.strip())})


def _git_exists(repo: Path, ref: str, rel_path: str) -> bool:
    proc = subprocess.run(
        ["git", "cat-file", "-e", f"{ref}:{rel_path}"],
        cwd=str(repo),
        text=True,
        capture_output=True,
    )
    return proc.returncode == 0


def _baseline_blob_sha(repo: Path, ref: str, rel_path: str) -> str | None:
    """Content (blob) SHA of ``rel_path`` at ``ref`` — changes iff the file content does."""
    proc = subprocess.run(
        ["git", "rev-parse", f"{ref}:{rel_path}"],
        cwd=str(repo),
        text=True,
        capture_output=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def _read_sync_manifest(private_root: Path, private_ref: str) -> dict[str, str]:
    """Read ``{rel_path: baseline_blob_sha}`` reconciliation manifest from the private repo."""
    proc = subprocess.run(
        ["git", "show", f"{private_ref}:{_SYNC_MANIFEST}"],
        cwd=str(private_root),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return {}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def _mark_synced(private_root: Path, findings: list[DriftFinding]) -> int:
    """Record each finding's baseline blob SHA in the private repo manifest + commit.

    After an operator reconciles an override with the new baseline, this marks it
    synced so it stops alerting until the baseline content changes again.
    """
    manifest_path = private_root / _SYNC_MANIFEST
    existing: dict[str, str] = {}
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    marked = 0
    for finding in findings:
        if finding.baseline_blob_sha:
            existing[finding.path] = finding.baseline_blob_sha
            marked += 1
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _run_git(private_root, ["add", "--", _SYNC_MANIFEST])
    if _run_git(private_root, ["diff", "--cached", "--name-only", "--", _SYNC_MANIFEST]).strip():
        _run_git(
            private_root,
            [
                "-c", "user.name=mosaic-prompts",
                "-c", "user.email=prompts@mosaic.local",
                "commit", "-m", f"baseline-sync: mark {marked} override(s) reconciled",
                "--", _SYNC_MANIFEST,
            ],
        )
    return marked


def _current_commit(repo: Path) -> str:
    return _run_git(repo, ["rev-parse", "HEAD"]).strip()


def _resolve_commit(repo: Path, ref: str) -> str:
    return _run_git(repo, ["rev-parse", ref]).strip()


def _private_repo_from_env() -> Path | None:
    value = os.getenv("MOSAIC_PRIVATE_PROMPT_REPO")
    if not value or not value.strip():
        return None
    return Path(value).expanduser().resolve()


def _read_state(path: Path) -> DriftState:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"state file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"state file is not valid JSON: {path}") from exc
    baseline_ref = raw.get("baseline_ref")
    if not isinstance(baseline_ref, str) or not baseline_ref.strip():
        raise RuntimeError(f"state file missing baseline_ref: {path}")
    return DriftState(baseline_ref=baseline_ref.strip())


def _write_state(path: Path, state: DriftState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(state), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _advance_state(state_file: Path, project_repo: Path) -> None:
    _write_state(state_file, DriftState(baseline_ref=_resolve_commit(_repo_root(project_repo), "HEAD")))


def check_drift(
    *,
    project_repo: Path,
    private_repo: Path,
    base_ref: str,
    private_ref: str = "HEAD",
) -> list[DriftFinding]:
    project_root = _repo_root(project_repo)
    private_root = _repo_root(private_repo)
    changed_paths = _changed_prompt_paths(project_root, base_ref)
    baseline_ref = _current_commit(project_root)
    private_commit = _run_git(private_root, ["rev-parse", private_ref]).strip()
    manifest = _read_sync_manifest(private_root, private_ref)

    findings: list[DriftFinding] = []
    for rel_path in changed_paths:
        match = PROMPT_RE.match(rel_path)
        if match is None:
            continue
        if not _git_exists(private_root, private_ref, rel_path):
            continue
        current_sha = _baseline_blob_sha(project_root, baseline_ref, rel_path) or ""
        # Staleness, not mere existence: skip overrides already reconciled with
        # this exact baseline content (recorded in the private repo manifest).
        if current_sha and manifest.get(rel_path) == current_sha:
            continue
        findings.append(
            DriftFinding(
                path=rel_path,
                cohort=match.group("cohort"),
                layer=match.group("layer"),
                agent=match.group("agent"),
                lang=match.group("lang"),
                baseline_ref=baseline_ref,
                private_ref=private_commit,
                private_path=str(private_root / rel_path),
                baseline_blob_sha=current_sha,
            )
        )
    return findings


def _print_text(findings: list[DriftFinding]) -> None:
    if not findings:
        print("prompt drift check passed: no changed baseline prompt is shadowed by a private override")
        return
    print("prompt drift check found private overrides shadowing changed baselines:")
    for finding in findings:
        print(
            "- "
            f"{finding.path} "
            f"(cohort={finding.cohort}, layer={finding.layer}, agent={finding.agent}, lang={finding.lang})"
        )
        print(f"  baseline={finding.baseline_ref[:12]} private={finding.private_ref[:12]}")
        print(f"  private_path={finding.private_path}")
        print(
            "  action=merge the public baseline tool/schema/contract changes into this override, "
            "then re-run with --mark-synced to record it reconciled (stops alerting until the "
            "baseline content changes again)"
        )


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["--"]:
        argv = argv[1:]
    parser = argparse.ArgumentParser(
        description="Find private prompt overrides that shadow changed project baseline prompts."
    )
    parser.add_argument("--repo", default=".", help="Project repo root (default: current directory)")
    parser.add_argument(
        "--base-ref",
        default=None,
        help="Base ref to diff against, e.g. origin/main. Optional when --state-file is set.",
    )
    parser.add_argument(
        "--private-repo",
        default=None,
        help="Private prompt repo root. Defaults to MOSAIC_PRIVATE_PROMPT_REPO.",
    )
    parser.add_argument("--private-ref", default="HEAD", help="Private prompt repo ref to inspect")
    parser.add_argument(
        "--state-file",
        default=None,
        help=(
            "Scheduled mode state file. When --base-ref is omitted, reads baseline_ref from this file. "
            "Updates it to the current project HEAD when the check passes, or when --accept is set."
        ),
    )
    parser.add_argument(
        "--accept",
        action="store_true",
        help=(
            "Acknowledge the current drift findings and advance --state-file to project HEAD. "
            "This is the explicit scheduled-mode waiver path."
        ),
    )
    parser.add_argument(
        "--mark-synced",
        action="store_true",
        help=(
            "Record the current findings' baseline blob SHAs in the private repo "
            "manifest (and commit), marking those overrides reconciled. Per-path, "
            "precise alternative to --accept: a marked override stops alerting "
            "until the baseline content changes again."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    private_repo = Path(args.private_repo).expanduser().resolve() if args.private_repo else _private_repo_from_env()
    if private_repo is None:
        print(
            "prompt drift check requires --private-repo or MOSAIC_PRIVATE_PROMPT_REPO",
            file=sys.stderr,
        )
        return 2

    project_repo = Path(args.repo).resolve()
    state_file = Path(args.state_file).expanduser().resolve() if args.state_file else None
    base_ref = args.base_ref
    if base_ref is None and state_file is not None:
        try:
            base_ref = _read_state(state_file).baseline_ref
        except Exception as exc:
            print(f"prompt drift check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
    if base_ref is None:
        print("prompt drift check requires --base-ref or --state-file", file=sys.stderr)
        return 2
    if args.accept and state_file is None:
        print("prompt drift check --accept requires --state-file", file=sys.stderr)
        return 2

    try:
        findings = check_drift(
            project_repo=project_repo,
            private_repo=private_repo,
            base_ref=base_ref,
            private_ref=args.private_ref,
        )
    except Exception as exc:
        print(f"prompt drift check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps([asdict(finding) for finding in findings], ensure_ascii=False, indent=2))
    else:
        _print_text(findings)

    if args.mark_synced and findings:
        try:
            marked = _mark_synced(_repo_root(private_repo), findings)
        except Exception as exc:
            print(f"prompt drift check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        if not args.json:
            print(f"marked {marked} override(s) as reconciled in {_SYNC_MANIFEST}")
        # Intentional short-circuit: don't advance --state-file here. The manifest
        # now records these overrides as reconciled, so the next run sees them as
        # synced (skipped) and, if nothing else drifts, advances the state cleanly.
        return 0

    if state_file is not None and (not findings or args.accept):
        try:
            _advance_state(state_file, project_repo)
        except Exception as exc:
            print(f"prompt drift check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        if findings and args.accept and not args.json:
            print("prompt drift check accepted: state advanced despite drift findings")
    return 1 if findings and not args.accept else 0


if __name__ == "__main__":
    raise SystemExit(main())
