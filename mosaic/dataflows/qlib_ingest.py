"""Thin orchestrator over the qlib Tushare collector (Plan §11.3 sub-step 3.5B).

The actual ingest logic lives in qlib's ``scripts/data_collector/tushare/collector.py``.
This module:

  * **Discovers** the qlib repo + collector script at well-known paths
    (env override > ``~/Projects/qlib`` > ``../qlib`` relative to MOSAIC).
  * **Wraps** the collector verbs (pipeline / download_data / normalize_data /
    dump_to_bin / update_data_to_bin / sync_calendar / pipeline_with_break)
    as Python functions that return dataclass results.
  * **Validates** the resulting qlib data dir post-ingest and emits the
    skipped-tickers manifest at ``data/qlib_skipped.txt`` (Plan §11.4
    design decision #5).

User decisions (2026-05-29) honoured here:
  * Tushare primary (no akshare fallback path in this orchestrator —
    user's collector handles fallback internally).
  * Manual incremental updates (operator runs ``python -m
    mosaic.dataflows.qlib_ingest --incremental``); no daemon.
  * Skip-on-gap > 1% — enforced by ``validate_after_ingest()`` post-pass
    rather than rejecting at fetch time.

Why vendored collectors:

  The Tushare stock + ETF collectors (and the qlib ``dump_bin`` /
  ``data_collector.{base,utils}`` they build on) are vendored into
  ``mosaic/dataflows/collectors/`` so MOSAIC's ingest is **self-contained** —
  no external qlib source checkout is required at run time (only the installed
  ``pyqlib`` package, for ``qlib.utils``). ``find_qlib_collector`` prefers the
  vendored copy; ``MOSAIC_QLIB_REPO`` / ``MOSAIC_QLIB_ETF_COLLECTOR`` still
  override it. See ``collectors/NOTICE.md`` for provenance + licensing.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

# Candidate paths where the qlib repo (with ``scripts/data_collector/tushare/``)
# can live. ``MOSAIC_QLIB_REPO`` env overrides everything.
_QLIB_REPO_CANDIDATES = (
    "~/Projects/qlib",
    "../qlib",  # sibling of MOSAIC-Agents repo
    "~/qlib",
)

DEFAULT_QLIB_DATA_DIR = Path.home() / ".qlib" / "qlib_data" / "cn_data"
DEFAULT_QLIB_ETF_DATA_DIR = Path.home() / ".qlib" / "qlib_data" / "cn_etf"
DEFAULT_RAW_DIR = Path.home() / ".cache" / "mosaic_tushare_raw"
DEFAULT_NORMALIZE_DIR = Path.home() / ".cache" / "mosaic_tushare_norm"

# The ETF collector ships separately (user-authored). Its standalone location
# is searched first; ``MOSAIC_QLIB_ETF_COLLECTOR`` (full path to collector.py)
# overrides. It exposes the same verbs and defaults its output to cn_etf.
_QLIB_ETF_COLLECTOR_CANDIDATES = (
    "~/.qlib/scripts/data_collector/tushare_etf/collector.py",
)

# Self-contained vendored collectors live inside the package (see
# ``collectors/NOTICE.md``). Preferred over any on-disk qlib checkout, but an
# explicit env override (MOSAIC_QLIB_REPO / MOSAIC_QLIB_ETF_COLLECTOR) still wins.
_VENDORED_DC_DIR = Path(__file__).resolve().parent / "collectors" / "data_collector"


@dataclass(frozen=True)
class CollectorPaths:
    repo_root: Path
    collector_script: Path


class CollectorNotFound(Exception):
    """Raised when the qlib tushare collector script can't be located."""


def find_qlib_collector(kind: str = "stock") -> CollectorPaths:
    """Return the path to a qlib Tushare collector + its repo root.

    Prefers the **vendored** collector in ``mosaic/dataflows/collectors/
    data_collector/{tushare,tushare_etf}/collector.py``. An explicit env
    override always wins: ``MOSAIC_QLIB_REPO`` (stock) /
    ``MOSAIC_QLIB_ETF_COLLECTOR`` (etf). Falls back to ``~/Projects/qlib``,
    ``<MOSAIC repo>/../qlib``, ``~/qlib`` (stock) and
    ``~/.qlib/scripts/.../tushare_etf`` (etf). Raises ``CollectorNotFound``.
    """
    if kind == "etf":
        env_collector = os.environ.get("MOSAIC_QLIB_ETF_COLLECTOR")
        etf_candidates: list[Path] = []
        if env_collector:
            etf_candidates.append(Path(env_collector).expanduser())
        # Self-contained vendored copy (preferred when no env override).
        etf_candidates.append(_VENDORED_DC_DIR / "tushare_etf" / "collector.py")
        for c in _QLIB_ETF_COLLECTOR_CANDIDATES:
            etf_candidates.append(Path(c).expanduser())
        # Also allow it living under a qlib repo like the stock collector.
        for repo in (os.environ.get("MOSAIC_QLIB_REPO"), *_QLIB_REPO_CANDIDATES):
            if repo:
                etf_candidates.append(
                    Path(repo).expanduser() / "scripts" / "data_collector"
                    / "tushare_etf" / "collector.py"
                )
        for collector in etf_candidates:
            collector = collector.expanduser()
            if collector.is_file():
                return CollectorPaths(repo_root=collector.parent, collector_script=collector)
        tried = "\n  ".join(str(c) for c in etf_candidates)
        raise CollectorNotFound(
            "qlib ETF collector not found. Tried:\n  " + tried + "\n"
            "Set MOSAIC_QLIB_ETF_COLLECTOR to the collector.py path."
        )

    env_root = os.environ.get("MOSAIC_QLIB_REPO")
    # Self-contained vendored copy first (unless an env override points elsewhere).
    vendored = _VENDORED_DC_DIR / "tushare" / "collector.py"
    if not env_root and vendored.is_file():
        return CollectorPaths(repo_root=vendored.parent, collector_script=vendored)

    candidates: list[Path] = []
    if env_root:
        candidates.append(Path(env_root).expanduser())
    for c in _QLIB_REPO_CANDIDATES:
        candidates.append(Path(c).expanduser())

    for repo_root in candidates:
        repo_root = repo_root.resolve()
        collector = repo_root / "scripts" / "data_collector" / "tushare" / "collector.py"
        if collector.is_file():
            return CollectorPaths(repo_root=repo_root, collector_script=collector)

    # Fall back to the vendored copy even if an env root was set but invalid.
    if vendored.is_file():
        return CollectorPaths(repo_root=vendored.parent, collector_script=vendored)

    tried = "\n  ".join(str(c) for c in candidates)
    raise CollectorNotFound(
        "qlib tushare collector not found. Tried:\n  " + tried + "\n"
        "Set MOSAIC_QLIB_REPO to the qlib repo root, or clone "
        "https://github.com/microsoft/qlib.git to ~/Projects/qlib and copy the user's "
        "tushare collector to <repo>/scripts/data_collector/tushare/collector.py."
    )


# ---------------------------------------------------------------------------
# Subprocess wrappers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IngestOutcome:
    verb: str
    returncode: int
    stdout_tail: str
    stderr_tail: str
    raw_dir: Optional[Path] = None
    normalize_dir: Optional[Path] = None
    qlib_dir: Optional[Path] = None


def _python_executable() -> str:
    return sys.executable or "python"


def _run_collector(
    verb: str,
    args: list[str],
    *,
    kind: str = "stock",
    cwd: Optional[Path] = None,
    timeout: Optional[int] = None,
    stream_stdout: bool = True,
) -> IngestOutcome:
    """Spawn the qlib tushare collector with ``verb`` + ``args``.

    Streams stdout to the parent process (via inherit) when ``stream_stdout``
    is True (default — gives operators live progress feedback during long
    full ingests). When False, captures both streams for testing.
    """
    paths = find_qlib_collector(kind)
    cmd = [_python_executable(), str(paths.collector_script), verb, *args]
    logger.info("running qlib collector: %s", " ".join(cmd))

    # Ensure TUSHARE_TOKEN is in the subprocess env even when called from a
    # context that didn't source .env (mosaic/__init__.py loads it for the
    # parent, but Popen captures parent env so this is fine).
    env = os.environ.copy()

    if stream_stdout:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd or paths.repo_root),
            env=env,
            timeout=timeout,
            check=False,
        )
        return IngestOutcome(
            verb=verb,
            returncode=proc.returncode,
            stdout_tail="",
            stderr_tail="",
        )
    else:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd or paths.repo_root),
            env=env,
            timeout=timeout,
            check=False,
            capture_output=True,
            text=True,
        )
        return IngestOutcome(
            verb=verb,
            returncode=proc.returncode,
            stdout_tail=proc.stdout[-4000:] if proc.stdout else "",
            stderr_tail=proc.stderr[-4000:] if proc.stderr else "",
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ingest_full(
    *,
    start: str = "1990-01-01",
    end: str,
    kind: str = "stock",
    qlib_dir: Optional[Path] = None,
    raw_dir: Path = DEFAULT_RAW_DIR,
    normalize_dir: Path = DEFAULT_NORMALIZE_DIR,
    max_workers: int = 4,
    timeout: int = 120,
    stream_stdout: bool = True,
) -> IngestOutcome:
    """Run the full pipeline: download_data → normalize_data → dump_to_bin.

    ``kind='etf'`` drives the ETF collector and defaults output to cn_etf.
    Roughly 30-90 minutes for the full A-share universe (~5500 tickers ×
    ~35 trading years). Free-tier Tushare may take longer; use ``max_workers``
    cautiously to respect rate limits.
    """
    if qlib_dir is None:
        qlib_dir = DEFAULT_QLIB_ETF_DATA_DIR if kind == "etf" else DEFAULT_QLIB_DATA_DIR
    qlib_dir = Path(qlib_dir).expanduser()
    raw_dir = Path(raw_dir).expanduser()
    normalize_dir = Path(normalize_dir).expanduser()
    qlib_dir.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    normalize_dir.mkdir(parents=True, exist_ok=True)

    args = [
        "--source_dir", str(raw_dir),
        "--normalize_dir", str(normalize_dir),
        "--qlib_dir", str(qlib_dir),
        "--start", start,
        "--end", end,
        "--max_workers", str(max_workers),
        "--timeout", str(timeout),
    ]
    outcome = _run_collector("pipeline", args, kind=kind, stream_stdout=stream_stdout)
    return IngestOutcome(
        verb=outcome.verb,
        returncode=outcome.returncode,
        stdout_tail=outcome.stdout_tail,
        stderr_tail=outcome.stderr_tail,
        raw_dir=raw_dir,
        normalize_dir=normalize_dir,
        qlib_dir=qlib_dir,
    )


def ingest_incremental(
    *,
    end: str,
    kind: str = "stock",
    qlib_dir: Optional[Path] = None,
    timeout: int = 120,
    stream_stdout: bool = True,
) -> IngestOutcome:
    """Append the latest trading days to an existing qlib data dir.

    ``kind='etf'`` updates the cn_etf dataset via the ETF collector. Internally
    the collector's ``update_data_to_bin`` verb reads ``calendars/day.txt`` to
    find the last covered date and only fetches rows after that.
    """
    if qlib_dir is None:
        qlib_dir = DEFAULT_QLIB_ETF_DATA_DIR if kind == "etf" else DEFAULT_QLIB_DATA_DIR
    qlib_dir = Path(qlib_dir).expanduser()
    if not (qlib_dir / "calendars" / "day.txt").exists():
        raise FileNotFoundError(
            f"qlib data dir not initialised yet: {qlib_dir}. "
            "Run --full first."
        )
    args = [
        "--qlib_data_1d_dir", str(qlib_dir),
        "--end_date", end,
        "--timeout", str(timeout),
    ]
    outcome = _run_collector("update_data_to_bin", args, kind=kind, stream_stdout=stream_stdout)
    return IngestOutcome(
        verb=outcome.verb,
        returncode=outcome.returncode,
        stdout_tail=outcome.stdout_tail,
        stderr_tail=outcome.stderr_tail,
        qlib_dir=qlib_dir,
    )


def sync_calendar(
    *,
    end: Optional[str] = None,
    qlib_dir: Path = DEFAULT_QLIB_DATA_DIR,
    stream_stdout: bool = True,
) -> IngestOutcome:
    """Refresh ``calendars/day.txt`` from Tushare without touching features."""
    qlib_dir = Path(qlib_dir).expanduser()
    args = ["--qlib_data_1d_dir", str(qlib_dir)]
    if end:
        args += ["--end_date", end]
    outcome = _run_collector("sync_calendar", args, stream_stdout=stream_stdout)
    return IngestOutcome(
        verb=outcome.verb,
        returncode=outcome.returncode,
        stdout_tail=outcome.stdout_tail,
        stderr_tail=outcome.stderr_tail,
        qlib_dir=qlib_dir,
    )


# ---------------------------------------------------------------------------
# Validation + skip-manifest
# ---------------------------------------------------------------------------


def validate_after_ingest(
    qlib_dir: Path = DEFAULT_QLIB_DATA_DIR,
    *,
    skip_manifest: Optional[Path] = None,
    gap_threshold: float = 0.01,
) -> dict:
    """Walk the ingested qlib data and produce a quality report.

    Computes per-ticker bar-count gap vs expected calendar length. Tickers
    whose gap exceeds ``gap_threshold`` (default 1%) are recorded in
    ``skip_manifest`` (default ``data/qlib_skipped.txt``) — Plan §11.4
    design decision #5.

    Returns a summary dict::

        {
            "qlib_dir": <path>,
            "calendar_days": <int>,
            "instruments": <int>,
            "checked": <int>,
            "skipped": <int>,
            "skip_manifest": <path>,
        }
    """
    import struct

    qlib_dir = Path(qlib_dir).expanduser()
    if not qlib_dir.is_dir():
        raise FileNotFoundError(f"qlib dir does not exist: {qlib_dir}")

    cal_file = qlib_dir / "calendars" / "day.txt"
    instruments_file = qlib_dir / "instruments" / "all.txt"
    features_dir = qlib_dir / "features"
    if not cal_file.exists() or not instruments_file.exists() or not features_dir.is_dir():
        raise FileNotFoundError(
            f"qlib dir layout incomplete in {qlib_dir} "
            "(missing calendars/day.txt, instruments/all.txt, or features/)"
        )

    calendar_days = sum(1 for _ in cal_file.read_text(encoding="utf-8").splitlines() if _.strip())

    if skip_manifest is None:
        skip_manifest = (
            Path(os.environ.get("MOSAIC_DATA_DIR") or _repo_root() / "data") / "qlib_skipped.txt"
        )
    skip_manifest = Path(skip_manifest).expanduser()
    skip_manifest.parent.mkdir(parents=True, exist_ok=True)

    instruments_lines = [
        line.split("\t")[0].strip()
        for line in instruments_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    skipped: list[tuple[str, int, int]] = []  # (ticker, expected, actual)
    checked = 0
    for ticker in instruments_lines:
        close_bin = features_dir / ticker / "close.day.bin"
        if not close_bin.exists():
            skipped.append((ticker, calendar_days, 0))
            continue
        # qlib bin: bytes 0-3 = float32 start_idx, then float32 values
        try:
            data = close_bin.read_bytes()
            n_values = max((len(data) - 4) // 4, 0)
            start_idx = int(round(struct.unpack("<f", data[:4])[0])) if n_values > 0 else 0
            expected = max(calendar_days - start_idx, 0)
            if expected > 0 and (expected - n_values) / expected > gap_threshold:
                skipped.append((ticker, expected, n_values))
            checked += 1
        except Exception as exc:
            logger.warning("validate: failed to inspect %s close.bin: %s", ticker, exc)
            skipped.append((ticker, calendar_days, 0))

    if skipped:
        with open(skip_manifest, "w", encoding="utf-8") as f:
            f.write("# qlib ingest skipped tickers (gap > {:.0%}).\n".format(gap_threshold))
            f.write("# format: <ticker>\\t<expected_bars>\\t<actual_bars>\\t<gap_pct>\n")
            for ticker, expected, actual in skipped:
                gap_pct = 1.0 - (actual / expected if expected else 0)
                f.write(f"{ticker}\t{expected}\t{actual}\t{gap_pct:.4f}\n")
    elif skip_manifest.exists():
        # Stale manifest from a prior run — clear it.
        skip_manifest.write_text(
            "# qlib ingest skipped tickers (gap > {:.0%}).\n".format(gap_threshold),
            encoding="utf-8",
        )

    return {
        "qlib_dir": str(qlib_dir),
        "calendar_days": calendar_days,
        "instruments": len(instruments_lines),
        "checked": checked,
        "skipped": len(skipped),
        "skip_manifest": str(skip_manifest),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Resolve MOSAIC repo root by walking up from this file."""
    return Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def _cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="mosaic.dataflows.qlib_ingest")
    sub = parser.add_subparsers(dest="cmd", required=True)

    full = sub.add_parser("full", help="full ingest from --start to --end")
    full.add_argument("--start", default="1990-01-01")
    full.add_argument("--end", required=True)
    full.add_argument("--qlib-dir", default=str(DEFAULT_QLIB_DATA_DIR))
    full.add_argument("--max-workers", type=int, default=4)
    full.add_argument("--timeout", type=int, default=120)

    inc = sub.add_parser("incremental", help="append from last covered day")
    inc.add_argument("--end", required=True)
    inc.add_argument("--qlib-dir", default=str(DEFAULT_QLIB_DATA_DIR))
    inc.add_argument("--timeout", type=int, default=120)

    cal = sub.add_parser("calendar", help="refresh calendars/day.txt only")
    cal.add_argument("--end", default=None)
    cal.add_argument("--qlib-dir", default=str(DEFAULT_QLIB_DATA_DIR))

    val = sub.add_parser("validate", help="validate ingested data + write skip manifest")
    val.add_argument("--qlib-dir", default=str(DEFAULT_QLIB_DATA_DIR))
    val.add_argument("--gap-threshold", type=float, default=0.01)

    args = parser.parse_args()

    try:
        if args.cmd == "full":
            outcome = ingest_full(
                start=args.start,
                end=args.end,
                qlib_dir=Path(args.qlib_dir),
                max_workers=args.max_workers,
                timeout=args.timeout,
            )
        elif args.cmd == "incremental":
            outcome = ingest_incremental(
                end=args.end,
                qlib_dir=Path(args.qlib_dir),
                timeout=args.timeout,
            )
        elif args.cmd == "calendar":
            outcome = sync_calendar(
                end=args.end,
                qlib_dir=Path(args.qlib_dir),
            )
        elif args.cmd == "validate":
            report = validate_after_ingest(
                qlib_dir=Path(args.qlib_dir),
                gap_threshold=args.gap_threshold,
            )
            for k, v in report.items():
                print(f"{k:20} {v}")
            return 0
        else:
            parser.error(f"unknown command: {args.cmd}")
            return 2
    except CollectorNotFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    if outcome.returncode != 0:
        print(f"collector exited {outcome.returncode}", file=sys.stderr)
        if outcome.stderr_tail:
            print(outcome.stderr_tail, file=sys.stderr)
        return outcome.returncode
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
