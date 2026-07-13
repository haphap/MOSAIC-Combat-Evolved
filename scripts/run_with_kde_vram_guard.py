#!/usr/bin/env python3
"""Run a command while enforcing GPU headroom for the KDE display server."""

from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

MINIMUM_FREE_MIB = 1024
GUARD_EXIT_CODE = 2
_KERNEL_ERRORS = ("Failed to allocate NVKMS memory for GEM object",)
_KWIN_ERRORS = (
    "Applying output configuration failed",
    "Failed to find a working output layer configuration",
)


@dataclass(frozen=True)
class GpuSample:
    timestamp: str
    memory_used_mib: int
    memory_free_mib: int
    utilization_pct: int
    temperature_c: int


class GuardSignal(Exception):
    def __init__(self, signum: int) -> None:
        super().__init__(f"received signal {signum}")
        self.signum = signum


def parse_gpu_sample(output: str, *, timestamp: str | None = None) -> GpuSample:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError(f"expected one GPU sample, received {len(lines)}")
    values = [value.strip() for value in lines[0].split(",")]
    if len(values) != 4:
        raise ValueError(f"expected four GPU fields, received {len(values)}")
    try:
        used, free, utilization, temperature = (int(float(value)) for value in values)
    except ValueError as exc:
        raise ValueError(f"invalid nvidia-smi sample: {lines[0]}") from exc
    return GpuSample(
        timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
        memory_used_mib=used,
        memory_free_mib=free,
        utilization_pct=utilization,
        temperature_c=temperature,
    )


def query_gpu(nvidia_smi: str) -> GpuSample:
    result = subprocess.run(
        [
            nvidia_smi,
            "--query-gpu=memory.used,memory.free,utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"nvidia-smi failed ({result.returncode}): {detail}")
    return parse_gpu_sample(result.stdout)


def find_kde_log_errors(journalctl: str, since: str) -> tuple[list[str], list[str]]:
    queries = (
        ("kernel", [journalctl, "-k", "--since", since, "--no-pager", "--output=cat"], _KERNEL_ERRORS),
        (
            "kwin",
            [
                journalctl,
                "--user",
                "--since",
                since,
                "_COMM=kwin_wayland",
                "--no-pager",
                "--output=cat",
            ],
            _KWIN_ERRORS,
        ),
    )
    matches: list[str] = []
    failures: list[str] = []
    for label, command, patterns in queries:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            failures.append(f"{label}: {detail or f'exit {result.returncode}'}")
            continue
        matches.extend(
            f"{label}: {line.strip()}"
            for line in result.stdout.splitlines()
            if any(pattern in line for pattern in patterns)
        )
    return matches, failures


def terminate_process_group(process: subprocess.Popen[bytes], grace_seconds: float) -> int:
    if process.poll() is not None:
        return int(process.returncode or 0)
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return int(process.wait())
    try:
        return int(process.wait(timeout=grace_seconds))
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return int(process.wait())


def _write_summary(path: Path, summary: dict[str, object]) -> None:
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def run_guard(args: argparse.Namespace) -> int:
    command = list(args.command)
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        raise ValueError("a command is required after --")

    output = args.output.resolve()
    summary_path = output.with_suffix(output.suffix + ".summary.json")
    if output.exists() or summary_path.exists():
        raise ValueError(f"guard evidence already exists: {output} or {summary_path}")
    output.parent.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc).isoformat()
    minimum_observed: int | None = None
    sample_count = 0
    violation: str | None = None
    error: str | None = None
    child_returncode: int | None = None
    process: subprocess.Popen[bytes] | None = None
    interrupted_exit: int | None = None

    def record(writer: csv.DictWriter, stream, sample: GpuSample) -> None:
        nonlocal minimum_observed, sample_count
        writer.writerow(asdict(sample))
        stream.flush()
        sample_count += 1
        minimum_observed = (
            sample.memory_free_mib
            if minimum_observed is None
            else min(minimum_observed, sample.memory_free_mib)
        )

    previous_handlers: dict[int, object] = {}

    def handle_signal(signum, _frame) -> None:
        raise GuardSignal(signum)

    for signum in (signal.SIGHUP, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, handle_signal)

    try:
        with output.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(GpuSample.__dataclass_fields__))
            writer.writeheader()
            try:
                sample = query_gpu(args.nvidia_smi)
                record(writer, stream, sample)
                if sample.memory_free_mib < args.minimum_free_mib:
                    violation = "free_vram_below_threshold"
                    error = (
                        f"initial free VRAM {sample.memory_free_mib} MiB is below "
                        f"{args.minimum_free_mib} MiB"
                    )
                else:
                    process = subprocess.Popen(command, start_new_session=True)
                    while process.poll() is None:
                        time.sleep(args.interval_seconds)
                        try:
                            sample = query_gpu(args.nvidia_smi)
                        except (RuntimeError, ValueError) as exc:
                            violation = "gpu_sampling_failed"
                            error = str(exc)
                            child_returncode = terminate_process_group(
                                process, args.termination_grace_seconds
                            )
                            break
                        record(writer, stream, sample)
                        if sample.memory_free_mib < args.minimum_free_mib:
                            violation = "free_vram_below_threshold"
                            error = (
                                f"free VRAM {sample.memory_free_mib} MiB is below "
                                f"{args.minimum_free_mib} MiB"
                            )
                            child_returncode = terminate_process_group(
                                process, args.termination_grace_seconds
                            )
                            break
                    if child_returncode is None:
                        child_returncode = int(process.wait())
            except KeyboardInterrupt:
                violation = "interrupted"
                interrupted_exit = 130
                if process is not None:
                    child_returncode = terminate_process_group(
                        process, args.termination_grace_seconds
                    )
            except GuardSignal as exc:
                violation = "interrupted"
                error = str(exc)
                interrupted_exit = 128 + exc.signum
                if process is not None:
                    child_returncode = terminate_process_group(
                        process, args.termination_grace_seconds
                    )
            except (RuntimeError, ValueError) as exc:
                violation = "gpu_sampling_failed"
                error = str(exc)
    finally:
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)

    kde_log_matches: list[str] = []
    kde_log_failures: list[str] = []
    if not args.skip_kde_log_check:
        kde_log_matches, kde_log_failures = find_kde_log_errors(args.journalctl, started_at)
        if violation is None and kde_log_matches:
            violation = "kde_display_error"
        if violation is None and kde_log_failures:
            violation = "kde_log_check_failed"

    ended_at = datetime.now(timezone.utc).isoformat()
    summary: dict[str, object] = {
        "command": command,
        "started_at": started_at,
        "ended_at": ended_at,
        "minimum_free_mib_required": args.minimum_free_mib,
        "minimum_free_mib_observed": minimum_observed,
        "sample_count": sample_count,
        "violation": violation,
        "error": error,
        "child_returncode": child_returncode,
        "kde_log_matches": kde_log_matches,
        "kde_log_check_failures": kde_log_failures,
    }
    _write_summary(summary_path, summary)
    print(
        f"KDE VRAM guard: min_free={minimum_observed} MiB "
        f"required={args.minimum_free_mib} MiB samples={sample_count} "
        f"violation={violation or 'none'} summary={summary_path}",
        file=sys.stderr,
    )
    if interrupted_exit is not None:
        return interrupted_exit
    if violation is not None:
        return GUARD_EXIT_CODE
    if child_returncode is None:
        return GUARD_EXIT_CODE
    return child_returncode if child_returncode >= 0 else 128 - child_returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="private CSV evidence path")
    parser.add_argument("--minimum-free-mib", type=int, default=MINIMUM_FREE_MIB)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--termination-grace-seconds", type=float, default=15.0)
    parser.add_argument("--nvidia-smi", default="nvidia-smi")
    parser.add_argument("--journalctl", default="journalctl")
    parser.add_argument("--skip-kde-log-check", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.minimum_free_mib <= 0:
        parser.error("--minimum-free-mib must be positive")
    if args.interval_seconds <= 0:
        parser.error("--interval-seconds must be positive")
    if args.termination_grace_seconds < 0:
        parser.error("--termination-grace-seconds cannot be negative")
    try:
        return run_guard(args)
    except ValueError as exc:
        parser.error(str(exc))
    return GUARD_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
