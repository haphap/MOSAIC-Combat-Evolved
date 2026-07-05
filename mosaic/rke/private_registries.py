"""Private MOSAIC registry helpers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence

from .registry_manifest import PRIVATE_LOCAL_REGISTRY_FILES


DEFAULT_REPORT_INTELLIGENCE_REGISTRY_DIR = "registry/report_intelligence"
FINGERPRINT_MANIFEST_NAME = "report_fingerprint_manifest.jsonl"
FINGERPRINT_MANIFEST_PATH = (
    f"{DEFAULT_REPORT_INTELLIGENCE_REGISTRY_DIR}/{FINGERPRINT_MANIFEST_NAME}"
)
PRIVATE_REGISTRY_MANIFEST_NAME = "registry_manifest.json"
PRIVATE_REGISTRY_JSON_SUFFIXES = frozenset({".json", ".jsonl"})


def resolve_report_intelligence_registry_dir(
    root: str | Path = ".",
    registry_dir: str | Path | None = None,
) -> Path:
    root_path = Path(root).expanduser().resolve()
    raw = str(registry_dir or "").strip()
    if not raw:
        raw = os.environ.get("MOSAIC_REGISTRY_DIR", "").strip()
    if not raw:
        repo = os.environ.get("MOSAIC_REGISTRIES_REPO", "").strip()
        raw = str(Path(repo) / DEFAULT_REPORT_INTELLIGENCE_REGISTRY_DIR) if repo else ""
    path = Path(raw or DEFAULT_REPORT_INTELLIGENCE_REGISTRY_DIR).expanduser()
    return (path if path.is_absolute() else root_path / path).resolve()


def _repo_path_for_registry_dir(
    root: str | Path = ".",
    registry_dir: str | Path | None = None,
) -> Path:
    root_path = Path(root).expanduser().resolve()
    repo = os.environ.get("MOSAIC_REGISTRIES_REPO", "").strip()
    if repo:
        repo_path = Path(repo).expanduser()
        return (repo_path if repo_path.is_absolute() else root_path / repo_path).resolve()
    registry_path = resolve_report_intelligence_registry_dir(root_path, registry_dir)
    if registry_path.name == "report_intelligence" and registry_path.parent.name == "registry":
        return registry_path.parent.parent
    return root_path


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def _stable_digest(value: Any, *, length: int = 16) -> str:
    return _stable_hash(value).removeprefix("sha256:")[:length]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _source_publish_datetime(row: Mapping[str, Any]) -> str:
    publish = str(row.get("publish_datetime") or row.get("publish_date") or "").strip()
    return publish if not publish or "T" in publish else f"{publish}T00:00:00+08:00"


def _author_ids(row: Mapping[str, Any]) -> list[str]:
    raw = row.get("author_ids")
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]
    author = str(row.get("author") or "").strip()
    if not author:
        return []
    parts = [part.strip() for part in author.replace("，", ",").replace("、", ",").split(",")]
    return [
        "AUTH-" + _stable_digest({"author": part}, length=12).upper()
        for part in dict.fromkeys(part for part in parts if part)
    ]


def _institution_id(row: Mapping[str, Any]) -> str:
    value = str(row.get("institution_id") or "").strip()
    if value:
        return value
    return "INST-" + _stable_digest(
        {"institution": row.get("institution") or ""},
        length=12,
    ).upper()


def _source_hash(row: Mapping[str, Any]) -> str:
    value = str(row.get("source_hash") or "").strip()
    if value:
        return value
    return _stable_hash(
        {
            "source_id": row.get("source_id") or "",
            "title": row.get("title") or "",
            "url": row.get("url") or "",
            "publish_datetime": _source_publish_datetime(row),
        }
    )


def _title_normalized_hash(row: Mapping[str, Any]) -> str:
    title = " ".join(str(row.get("title") or "").casefold().split())
    return _stable_hash(title)


def _author_ids_hash(row: Mapping[str, Any]) -> str:
    return _stable_hash(_author_ids(row))


def _report_id(row: Mapping[str, Any]) -> str:
    value = str(row.get("report_id") or "").strip()
    if value:
        return value
    source_id = str(row.get("source_id") or "")
    publish = str(row.get("publish_date") or "UNKNOWN").replace("-", "")
    digest = _stable_digest(
        {
            "source_id": source_id,
            "title": row.get("title"),
            "url": row.get("url"),
        }
    )
    return f"RPT-TSRR-{publish}-{digest}"


def _nested_sha(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if isinstance(value, Mapping):
        return str(value.get("sha256") or "")
    return ""


def _source_span_ids(row: Mapping[str, Any]) -> list[str]:
    value = row.get("source_span_ids")
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    value = row.get("source_span_id")
    return [str(value)] if str(value or "").strip() else []


def _repo_root_from_registry_dir(registry_dir: Path) -> Path:
    if registry_dir.name == "report_intelligence" and registry_dir.parent.name == "registry":
        return registry_dir.parent.parent
    return registry_dir.parent


def _source_rows(repo_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relative in (
        "registry/sources/tushare_research_reports.jsonl",
        "registry/sources/local_macro_strategy_reports.jsonl",
    ):
        rows.extend(_read_jsonl(repo_root / relative))
    return rows


def build_report_fingerprint_manifest(registry_dir: str | Path) -> list[dict[str, Any]]:
    registry_path = Path(registry_dir).expanduser().resolve()
    repo_root = _repo_root_from_registry_dir(registry_path)
    source_by_id = {
        str(row.get("source_id") or "").strip(): row
        for row in _source_rows(repo_root)
        if str(row.get("source_id") or "").strip()
    }
    metadata = _read_jsonl(registry_path / "report_metadata.jsonl")
    metadata_by_source = {
        str(row.get("source_id") or "").strip(): row
        for row in metadata
        if str(row.get("source_id") or "").strip()
    }
    status_by_source = {
        str(row.get("source_id") or "").strip(): row
        for row in _read_jsonl(registry_path / "processing_status.jsonl")
        if str(row.get("source_id") or "").strip()
    }
    claims_by_report: dict[str, list[dict[str, Any]]] = {}
    for claim in _read_jsonl(registry_path / "forecast_claims.jsonl"):
        report_id = str(claim.get("report_id") or "").strip()
        if report_id:
            claims_by_report.setdefault(report_id, []).append(claim)
    footprints_by_report: dict[str, list[dict[str, Any]]] = {}
    for footprint in _read_jsonl(registry_path / "analytical_footprints.jsonl"):
        report_id = str(footprint.get("report_id") or "").strip()
        if report_id:
            footprints_by_report.setdefault(report_id, []).append(footprint)

    rows: list[dict[str, Any]] = []
    for source_id in sorted(source_by_id.keys() | metadata_by_source.keys()):
        source = source_by_id.get(source_id, {})
        meta = metadata_by_source.get(source_id, {})
        merged = {**source, **meta, "source_id": source_id}
        report_id = _report_id(merged)
        status = status_by_source.get(source_id, {})
        claim_index = [
            {
                "forecast_claim_id": str(claim.get("forecast_claim_id") or ""),
                "source_id": source_id,
                "report_id": report_id,
                "source_span_ids": _source_span_ids(claim),
            }
            for claim in claims_by_report.get(report_id, [])
            if str(claim.get("forecast_claim_id") or "").strip()
        ]
        footprint_index = [
            {
                "footprint_id": str(footprint.get("footprint_id") or ""),
                "source_id": source_id,
                "report_id": report_id,
                "source_span_ids": _source_span_ids(footprint),
            }
            for footprint in footprints_by_report.get(report_id, [])
            if str(footprint.get("footprint_id") or "").strip()
        ]
        rows.append(
            {
                "source_id": source_id,
                "report_id": report_id,
                "source_hash": _source_hash(merged),
                "publish_datetime": _source_publish_datetime(merged),
                "institution_id": _institution_id(merged),
                "title_normalized_hash": _title_normalized_hash(merged),
                "author_ids_hash": _author_ids_hash(merged),
                "pdf_sha256": _nested_sha(meta, "pdf") or str(source.get("pdf_sha256") or ""),
                "markdown_sha256": _nested_sha(meta, "markdown"),
                "source_span_root": source_id,
                "processing_status": str(
                    status.get("llm_status")
                    or (meta.get("extraction") or {}).get("llm_status")
                    or ""
                ),
                "forecast_claim_ids": [
                    item["forecast_claim_id"] for item in claim_index
                ],
                "footprint_ids": [item["footprint_id"] for item in footprint_index],
                "forecast_claim_index": claim_index,
                "footprint_index": footprint_index,
            }
        )
    return rows


def write_report_fingerprint_manifest(registry_dir: str | Path) -> dict[str, Any]:
    registry_path = Path(registry_dir).expanduser().resolve()
    rows = build_report_fingerprint_manifest(registry_path)
    output = registry_path / FINGERPRINT_MANIFEST_NAME
    _write_jsonl(output, rows)
    return {"path": str(output), "rows": len(rows), "sha256": _sha256_file(output)}


def load_report_fingerprint_index(registry_dir: str | Path) -> dict[str, set[str]]:
    registry_path = Path(registry_dir).expanduser().resolve()
    rows = _read_jsonl(registry_path / FINGERPRINT_MANIFEST_NAME)
    status_rows = _read_jsonl(registry_path / "processing_status.jsonl")
    return {
        "source_ids": {
            str(row.get("source_id") or "").strip()
            for row in rows
            if str(row.get("source_id") or "").strip()
        },
        "source_hashes": {
            str(row.get("source_hash") or "").strip()
            for row in rows
            if str(row.get("source_hash") or "").strip()
        },
        "pdf_sha256": {
            str(row.get("pdf_sha256") or "").strip()
            for row in rows
            if str(row.get("pdf_sha256") or "").strip()
        },
        "identity_keys": {
            "|".join(
                (
                    str(row.get("institution_id") or ""),
                    str(row.get("publish_datetime") or ""),
                    str(row.get("title_normalized_hash") or ""),
                )
            )
            for row in rows
        },
        "processed_source_ids": {
            str(row.get("source_id") or "").strip()
            for row in status_rows
            if str(row.get("source_id") or "").strip()
            and str(row.get("llm_status") or "") == "processed"
        },
    }


def duplicate_report_fingerprint_reason(
    source_row: Mapping[str, Any],
    index: Mapping[str, set[str]],
) -> str:
    source_id = str(source_row.get("source_id") or "").strip()
    if source_id and source_id in index.get("source_ids", set()):
        return "source_id"
    if source_id and source_id in index.get("processed_source_ids", set()):
        return "processing_status"
    source_hash = _source_hash(source_row)
    if source_hash and source_hash in index.get("source_hashes", set()):
        return "source_hash"
    pdf_sha = str(source_row.get("pdf_sha256") or source_row.get("source_hash") or "").strip()
    if pdf_sha and pdf_sha in index.get("pdf_sha256", set()):
        return "pdf_sha256"
    identity_key = "|".join(
        (
            _institution_id(source_row),
            _source_publish_datetime(source_row),
            _title_normalized_hash(source_row),
        )
    )
    if identity_key in index.get("identity_keys", set()):
        return "institution_publish_title"
    return ""


def _file_manifest_row(root: Path, path: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    row: dict[str, Any] = {
        "path": relative,
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }
    if path.suffix == ".jsonl":
        rows = _read_jsonl(path)
        row["row_count"] = len(rows)
        row["source_id_count"] = len(
            {str(item.get("source_id") or "") for item in rows if item.get("source_id")}
        )
        row["forecast_claim_count"] = len(
            [item for item in rows if item.get("forecast_claim_id")]
        )
        row["footprint_count"] = len([item for item in rows if item.get("footprint_id")])
    elif path.suffix == ".json":
        row["row_count"] = 1
    return row


def _write_private_registry_manifest(output_dir: Path, copied_paths: Sequence[Path]) -> dict[str, Any]:
    files = [_file_manifest_row(output_dir, path) for path in sorted(copied_paths)]
    source_ids: set[str] = set()
    forecast_claim_ids: set[str] = set()
    footprint_ids: set[str] = set()
    for path in copied_paths:
        if path.suffix != ".jsonl":
            continue
        for row in _read_jsonl(path):
            source_id = str(row.get("source_id") or "").strip()
            forecast_claim_id = str(row.get("forecast_claim_id") or "").strip()
            footprint_id = str(row.get("footprint_id") or "").strip()
            if source_id:
                source_ids.add(source_id)
            if forecast_claim_id:
                forecast_claim_ids.add(forecast_claim_id)
            if footprint_id:
                footprint_ids.add(footprint_id)
    vintage_input = [
        {
            "path": row["path"],
            "sha256": row["sha256"],
            "row_count": row.get("row_count", 0),
        }
        for row in files
    ]
    manifest = {
        "schema_version": "mosaic_private_registries_manifest_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(files),
        "row_count": sum(int(row.get("row_count") or 0) for row in files),
        "source_id_count": len(source_ids),
        "forecast_claim_count": len(forecast_claim_ids),
        "footprint_count": len(footprint_ids),
        "data_vintage_hash": _stable_hash(vintage_input),
        "files": files,
        "cache_manifest": {
            "included": False,
            "excluded_paths": [
                ".mosaic/rke/report_intelligence/pdfs",
                ".mosaic/rke/report_intelligence/markdown",
                ".mosaic/rke/report_intelligence/mineru",
            ],
            "missing_reason": "heavy local PDF/Markdown/MinerU cache excluded from v1 export",
        },
    }
    path = output_dir / PRIVATE_REGISTRY_MANIFEST_NAME
    _write_json(path, manifest)
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "file_count": manifest["file_count"],
        "data_vintage_hash": manifest["data_vintage_hash"],
    }


def export_private_registries(
    *,
    root: str | Path = ".",
    output_dir: str | Path,
    registry_dir: str | Path | None = None,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    output_path = Path(output_dir).expanduser().resolve()
    registry_path = resolve_report_intelligence_registry_dir(root_path, registry_dir)
    source_repo = _repo_root_from_registry_dir(registry_path)
    copied: list[Path] = []
    blockers: list[str] = []

    if registry_path.exists():
        write_report_fingerprint_manifest(registry_path)
    for relative in sorted(PRIVATE_LOCAL_REGISTRY_FILES | {FINGERPRINT_MANIFEST_PATH}):
        if Path(relative).suffix not in PRIVATE_REGISTRY_JSON_SUFFIXES:
            continue
        source = source_repo / relative
        if not source.exists() or not source.is_file():
            continue
        target = output_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(target)
    if not copied:
        blockers.append("no private registry JSON/JSONL files found")
    manifest = _write_private_registry_manifest(output_path, copied)
    return {
        "accepted": not blockers,
        "root": str(root_path),
        "source_repo": str(source_repo),
        "output_dir": str(output_path),
        "registry_dir": str(registry_path),
        "copied_file_count": len(copied),
        "copied_files": [path.relative_to(output_path).as_posix() for path in copied],
        "manifest": manifest,
        "blockers": blockers,
        "blocker_count": len(blockers),
    }


def _git_output(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _duplicate_count(rows: Sequence[Mapping[str, Any]], key: str) -> int:
    counts = Counter(str(row.get(key) or "") for row in rows if str(row.get(key) or ""))
    return sum(count - 1 for count in counts.values() if count > 1)


def registries_preflight(
    *,
    root: str | Path = ".",
    registry_dir: str | Path | None = None,
) -> dict[str, Any]:
    registry_path = resolve_report_intelligence_registry_dir(root, registry_dir)
    repo_path = _repo_path_for_registry_dir(root, registry_dir)
    manifest_path = repo_path / PRIVATE_REGISTRY_MANIFEST_NAME
    fingerprint_path = registry_path / FINGERPRINT_MANIFEST_NAME
    blockers: list[str] = []
    missing_files = []
    if not repo_path.exists():
        blockers.append("registries repo missing")
    if not registry_path.exists():
        blockers.append("report-intelligence registry dir missing")
    if not manifest_path.exists():
        blockers.append("registry_manifest.json missing")
    for relative in (
        "report_metadata.jsonl",
        "forecast_claims.jsonl",
        "analytical_footprints.jsonl",
        "processing_status.jsonl",
        FINGERPRINT_MANIFEST_NAME,
    ):
        if not (registry_path / relative).exists():
            missing_files.append(relative)
    rows = _read_jsonl(fingerprint_path)
    duplicate_count = (
        _duplicate_count(rows, "source_id")
        + _duplicate_count(rows, "report_id")
        + _duplicate_count(rows, "source_hash")
    )
    return {
        "accepted": not any("missing" in blocker for blocker in blockers),
        "repo_path": str(repo_path),
        "registry_dir": str(registry_path),
        "git_revision": _git_output(repo_path, "rev-parse", "HEAD") if repo_path.exists() else "",
        "dirty": bool(_git_output(repo_path, "status", "--porcelain")) if repo_path.exists() else False,
        "dirty_blocker": "registries repo dirty" if repo_path.exists() and _git_output(repo_path, "status", "--porcelain") else "",
        "manifest_path": str(manifest_path),
        "manifest_hash": _sha256_file(manifest_path) if manifest_path.exists() else "",
        "fingerprint_manifest_path": str(fingerprint_path),
        "missing_file_count": len(missing_files),
        "missing_files": missing_files,
        "duplicate_fingerprint_count": duplicate_count,
        "blockers": blockers,
        "blocker_count": len(blockers),
    }
