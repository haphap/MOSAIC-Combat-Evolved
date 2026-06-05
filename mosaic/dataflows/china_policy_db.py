"""Reader helpers for the external china-policy-db repository."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from .config import get_config
from .exceptions import DataVendorUnavailable

logger = logging.getLogger(__name__)


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


def _local_candidates(root: Path, jsonl_rel_path: str) -> list[Path]:
    return [
        root / jsonl_rel_path,
        root / "data" / jsonl_rel_path,
    ]


def load_external_records(jsonl_rel_path: str) -> tuple[list[dict[str, Any]], str] | None:
    """Load parsed records from a configured china-policy-db source.

    ``jsonl_rel_path`` is relative to the published ``data/`` directory, for
    example ``pboc_ops/parsed/articles.jsonl``.
    """

    local_dir = _configured_value("china_policy_db_dir", "MOSAIC_CHINA_POLICY_DB_DIR")
    if local_dir:
        root = Path(local_dir).expanduser()
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
