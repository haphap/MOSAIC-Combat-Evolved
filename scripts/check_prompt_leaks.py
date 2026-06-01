"""Prompt asset leak guard for project-repo PRs.

This is the Phase 6 enforcement layer for private prompt protection. It is
intentionally provenance-based: normal human edits to ``prompts/mosaic/**`` are
allowed, while autoresearch artifacts and private prompt repo material are
blocked.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PRIVATE_PATH_PREFIXES = (
    ".mosaic/",
    "private-prompts/",
    "prompt-store/",
    "data/private-prompts/",
)

AUTORESEARCH_BRANCH_PATTERNS = (
    re.compile(r"(^|/)cohort/[^/]+/auto/[^/]+/\d{4}-\d{2}-\d{2}$"),
    re.compile(r"(^|/)autoresearch(/|$)"),
)

AUTORESEARCH_DIFF_MARKERS = (
    re.compile(r"\bautoresearch fake-llm marker\b", re.IGNORECASE),
    re.compile(r"\bmodification_summary\b", re.IGNORECASE),
    re.compile(r"\bmutation rationale\b", re.IGNORECASE),
    re.compile(r"\bprompt_sha256\b", re.IGNORECASE),
    re.compile(r"\bprompt_repo_id\b", re.IGNORECASE),
    re.compile(r"\bMOSAIC_PRIVATE_PROMPT_REPO\b"),
)

AUTORESEARCH_COMMIT_MARKERS = (
    re.compile(r"^autoresearch:", re.IGNORECASE),
    re.compile(r"\bprompt_repo_id\b", re.IGNORECASE),
    re.compile(r"\bprompt_sha256\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class Finding:
    code: str
    detail: str


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


def _diff_spec(base_ref: str | None) -> list[str]:
    if base_ref:
        return [f"{base_ref}...HEAD"]
    return ["HEAD"]


def _changed_paths(repo: Path, base_ref: str | None) -> list[str]:
    out = _run_git(repo, ["diff", "--name-only", "--diff-filter=ACMRT", *_diff_spec(base_ref)])
    return [line.strip() for line in out.splitlines() if line.strip()]


def _added_lines(repo: Path, base_ref: str | None, pathspecs: Iterable[str]) -> list[tuple[str, str]]:
    out = _run_git(repo, ["diff", "--no-ext-diff", "--unified=0", *_diff_spec(base_ref), "--", *pathspecs])
    current_path = ""
    added: list[tuple[str, str]] = []
    for line in out.splitlines():
        if line.startswith("+++ b/"):
            current_path = line[6:]
            continue
        if line.startswith("+") and not line.startswith("+++"):
            added.append((current_path, line[1:]))
    return added


def _commit_subjects(repo: Path, base_ref: str | None) -> list[str]:
    if not base_ref:
        return []
    out = _run_git(repo, ["log", "--format=%s", f"{base_ref}..HEAD"])
    return [line.strip() for line in out.splitlines() if line.strip()]


def _gitmodules_paths(repo: Path, base_ref: str | None) -> list[str]:
    paths: list[str] = []
    for path, line in _added_lines(repo, base_ref, [".gitmodules"]):
        if path != ".gitmodules":
            continue
        stripped = line.strip()
        if stripped.startswith("path"):
            _, _, value = stripped.partition("=")
            if value.strip():
                paths.append(value.strip().rstrip("/") + "/")
    return paths


def _is_private_path(path: str) -> bool:
    normalized = path.lstrip("./")
    return any(normalized == prefix.rstrip("/") or normalized.startswith(prefix) for prefix in PRIVATE_PATH_PREFIXES)


def _is_autoresearch_branch(name: str) -> bool:
    return any(pattern.search(name) for pattern in AUTORESEARCH_BRANCH_PATTERNS)


def check_repo(repo: Path, base_ref: str | None = None) -> list[Finding]:
    findings: list[Finding] = []
    paths = _changed_paths(repo, base_ref)

    for path in paths:
        if _is_private_path(path):
            findings.append(
                Finding(
                    "private-path",
                    f"private prompt repo/material must not be tracked in project repo: {path}",
                )
            )

    for submodule_path in _gitmodules_paths(repo, base_ref):
        if _is_private_path(submodule_path):
            findings.append(
                Finding(
                    "private-submodule",
                    f"private prompt repo must not be added as a project submodule: {submodule_path}",
                )
            )

    prompt_paths = [p for p in paths if p.startswith("prompts/mosaic/")]
    if prompt_paths:
        for path, line in _added_lines(repo, base_ref, prompt_paths):
            for marker in AUTORESEARCH_DIFF_MARKERS:
                if marker.search(line):
                    findings.append(
                        Finding(
                            "autoresearch-prompt-diff",
                            f"autoresearch/private prompt marker found in {path}: {line[:160]}",
                        )
                    )
                    break

    for subject in _commit_subjects(repo, base_ref):
        for marker in AUTORESEARCH_COMMIT_MARKERS:
            if marker.search(subject):
                findings.append(
                    Finding(
                        "autoresearch-commit",
                        f"autoresearch/private prompt commit marker in commit subject: {subject}",
                    )
                )
                break

    for ref in _run_git(repo, ["for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes"]).splitlines():
        name = ref.strip()
        if name and _is_autoresearch_branch(name):
            findings.append(
                Finding(
                    "autoresearch-branch",
                    f"autoresearch runtime branch must live in private prompt repo, not project repo: {name}",
                )
            )

    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail if private/autoresearch prompts leak into the project repo.")
    parser.add_argument("--repo", default=".", help="Project repo root (default: current directory)")
    parser.add_argument(
        "--base-ref",
        default=None,
        help="Base ref for PR checks, e.g. origin/main. Defaults to working tree vs HEAD.",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    findings = check_repo(repo, args.base_ref)
    if findings:
        print("prompt leak guard failed:", file=sys.stderr)
        for finding in findings:
            print(f"- [{finding.code}] {finding.detail}", file=sys.stderr)
        return 1
    print("prompt leak guard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
