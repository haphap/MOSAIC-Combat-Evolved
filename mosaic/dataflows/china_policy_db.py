"""Reader helpers for the external china-policy-db repository."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from .config import get_config
from .exceptions import DataVendorUnavailable

logger = logging.getLogger(__name__)

DEFAULT_REPO_URL = "https://github.com/haphap/china-policy-db.git"
_SYNC_STATE_FILE = "mosaic-sync.json"
_GIT_TIMEOUT_SECONDS = 120
_COMMIT_NAME = "mosaic-policy-db"
_COMMIT_EMAIL = "policy-db@mosaic.local"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"", "0", "false", "no", "off"}


def _config_bool(config_key: str, env_key: str, default: bool) -> bool:
    raw = os.getenv(env_key)
    if raw is not None:
        return _env_bool(env_key, default)
    return bool(get_config().get(config_key, default))


def _config_float(config_key: str, env_key: str, default: float) -> float:
    raw = os.getenv(env_key)
    if raw is None:
        raw = get_config().get(config_key, default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _configured_path(config_key: str, env_key: str) -> Path | None:
    raw = _configured_value(config_key, env_key)
    return Path(raw).expanduser() if raw else None


def _parse_jsonl(text: str, source: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except ValueError as exc:
            raise DataVendorUnavailable(f"Invalid china-policy-db JSONL at {source}:{lineno}: {exc}") from exc
        if isinstance(record, dict):
            records.append(record)
    return records


def _configured_value(config_key: str, env_key: str) -> str:
    config = get_config()
    raw = os.getenv(env_key) or config.get(config_key) or ""
    return str(raw).strip()


def local_repo_root() -> Path:
    """Return the local china-policy-db clone/cache root.

    A configured ``MOSAIC_CHINA_POLICY_DB_DIR`` wins. Otherwise MOSAIC keeps a
    local clone under ``<data_cache_dir>/china-policy-db`` and uses the public
    GitHub repo only to populate/refresh that local copy.
    """

    configured = _configured_path("china_policy_db_dir", "MOSAIC_CHINA_POLICY_DB_DIR")
    if configured is not None:
        return configured

    cache_dir = get_config().get("data_cache_dir")
    if not cache_dir:
        raise DataVendorUnavailable("data_cache_dir is not configured.")
    return Path(str(cache_dir)).expanduser() / "china-policy-db"


def _repo_url() -> str:
    return _configured_value("china_policy_db_repo_url", "MOSAIC_CHINA_POLICY_DB_REPO_URL") or DEFAULT_REPO_URL


def _is_git_repo(root: Path) -> bool:
    return (root / ".git").exists()


def _sync_state_path(root: Path) -> Path:
    git_dir = root / ".git"
    if git_dir.is_dir():
        return git_dir / _SYNC_STATE_FILE
    return root / f".{_SYNC_STATE_FILE}"


def _load_sync_state(root: Path) -> dict[str, Any]:
    path = _sync_state_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_sync_state(root: Path, payload: dict[str, Any]) -> None:
    path = _sync_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_recent(timestamp: Any, stale_after_hours: float) -> bool:
    if stale_after_hours < 0 or not timestamp:
        return False
    from datetime import datetime, timezone

    try:
        dt = datetime.fromisoformat(str(timestamp))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - dt
    return age.total_seconds() < stale_after_hours * 3600


def _run_git(args: list[str], *, cwd: Path | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    if proc.returncode != 0:
        raise DataVendorUnavailable(
            f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout


def _abort_rebase(root: Path) -> None:
    try:
        _run_git(["rebase", "--abort"], cwd=root)
        logger.warning("Aborted wedged china-policy-db rebase at %s", root)
    except (OSError, DataVendorUnavailable, subprocess.TimeoutExpired):
        return


def _is_shallow_repo(root: Path) -> bool:
    try:
        return _run_git(["rev-parse", "--is-shallow-repository"], cwd=root).strip() == "true"
    except (OSError, DataVendorUnavailable, subprocess.TimeoutExpired):
        return False


def _unshallow_if_needed(root: Path) -> None:
    if _is_shallow_repo(root):
        _run_git(["fetch", "--unshallow"], cwd=root)


def ensure_local_repo(*, stale_after_hours: float | None = None) -> tuple[Path, str] | None:
    """Ensure a local china-policy-db checkout exists and is recently pulled.

    Returns ``(root, source_note)``. Failures are soft so the data tools can
    fall back to their existing PBOC/gov.cn crawlers.
    """

    root = local_repo_root()
    auto_sync = _config_bool(
        "china_policy_db_auto_sync",
        "MOSAIC_CHINA_POLICY_DB_AUTO_SYNC",
        True,
    )
    stale_hours = (
        _config_float(
            "china_policy_db_git_stale_hours",
            "MOSAIC_CHINA_POLICY_DB_GIT_STALE_HOURS",
            6.0,
        )
        if stale_after_hours is None
        else stale_after_hours
    )

    if root.exists() and not _is_git_repo(root):
        return root, str(root)

    if not root.exists():
        if not auto_sync:
            return None
        try:
            root.parent.mkdir(parents=True, exist_ok=True)
            _run_git(["clone", "--depth=1", _repo_url(), str(root)])
            _write_sync_state(root, {"last_pull_at": _utc_now_iso(), "repo_url": _repo_url()})
        except (OSError, DataVendorUnavailable, subprocess.TimeoutExpired) as exc:
            logger.warning("Failed to clone china-policy-db into %s: %s", root, exc)
            return None
        return root, str(root)

    if auto_sync and _is_git_repo(root):
        state = _load_sync_state(root)
        if not _is_recent(state.get("last_pull_at"), stale_hours):
            try:
                _run_git(["pull", "--rebase", "--autostash"], cwd=root)
                state.update({"last_pull_at": _utc_now_iso(), "repo_url": _repo_url()})
                _write_sync_state(root, state)
            except (OSError, DataVendorUnavailable, subprocess.TimeoutExpired) as exc:
                _abort_rebase(root)
                logger.warning("Failed to pull china-policy-db at %s: %s", root, exc)
    return root, str(root)


def commit_and_maybe_push_updates(
    root: Path,
    rel_paths: list[str],
    *,
    message: str,
) -> dict[str, Any]:
    """Commit local china-policy-db data changes, and optionally push them.

    Local commits are made only when remote pushes are enabled, avoiding silent
    divergence from origin. Remote pushes require
    ``MOSAIC_CHINA_POLICY_DB_PUSH_UPDATES=1``.
    """

    result: dict[str, Any] = {
        "changed": False,
        "skipped_commit": False,
        "committed": False,
        "pushed": False,
        "error": None,
    }
    if not _is_git_repo(root):
        return result

    try:
        status = _run_git(["status", "--porcelain", "--", *rel_paths], cwd=root).strip()
        if not status:
            return result
        result["changed"] = True

        push_updates = _config_bool(
            "china_policy_db_push_updates",
            "MOSAIC_CHINA_POLICY_DB_PUSH_UPDATES",
            False,
        )
        if not push_updates:
            result["skipped_commit"] = True
            return result

        _unshallow_if_needed(root)
        _run_git(["add", "--", *rel_paths], cwd=root)
        staged = _run_git(["diff", "--cached", "--name-only", "--", *rel_paths], cwd=root).strip()
        if staged:
            _run_git(
                [
                    "-c",
                    f"user.name={_COMMIT_NAME}",
                    "-c",
                    f"user.email={_COMMIT_EMAIL}",
                    "commit",
                    "-m",
                    message,
                ],
                cwd=root,
            )
            result["committed"] = True

        _run_git(["push"], cwd=root)
        result["pushed"] = True
    except (OSError, DataVendorUnavailable, subprocess.TimeoutExpired) as exc:
        result["error"] = str(exc)
        logger.warning("Failed to commit/push china-policy-db updates at %s: %s", root, exc)
    return result


def _local_candidates(root: Path, jsonl_rel_path: str) -> list[Path]:
    return [
        root / jsonl_rel_path,
        root / "data" / jsonl_rel_path,
    ]


def load_external_records(
    jsonl_rel_path: str,
    *,
    local_root: Path | None = None,
    discover_local: bool = True,
) -> tuple[list[dict[str, Any]], str] | None:
    """Load parsed records from a configured china-policy-db source.

    ``jsonl_rel_path`` is relative to the published ``data/`` directory, for
    example ``pboc_ops/parsed/articles.jsonl``.
    """

    root = local_root
    if root is None and discover_local:
        local = ensure_local_repo()
        if local:
            root, _source = local
    if root is not None:
        for path in _local_candidates(root, jsonl_rel_path):
            if path.is_file():
                return _parse_jsonl(path.read_text(encoding="utf-8"), str(path)), str(path)
        logger.warning("Configured china-policy-db path has no %s under %s", jsonl_rel_path, root)

    raw_base_url = _configured_value(
        "china_policy_db_raw_base_url",
        "MOSAIC_CHINA_POLICY_DB_RAW_BASE_URL",
    )
    if not raw_base_url:
        return None

    url = urljoin(raw_base_url.rstrip("/") + "/", jsonl_rel_path)
    try:
        import requests  # noqa: PLC0415

        response = requests.get(url, timeout=20)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load china-policy-db records from %s: %s", url, exc)
        return None
    return _parse_jsonl(response.text, url), url
