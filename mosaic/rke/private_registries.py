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


def _managed_private_registry_paths() -> tuple[str, ...]:
    return tuple(
        sorted(
            relative
            for relative in PRIVATE_LOCAL_REGISTRY_FILES | {FINGERPRINT_MANIFEST_PATH}
            if Path(relative).suffix in PRIVATE_REGISTRY_JSON_SUFFIXES
        )
    )


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
    explicit_registry_dir = bool(str(registry_dir or "").strip())
    repo = (
        ""
        if explicit_registry_dir
        else os.environ.get("MOSAIC_REGISTRIES_REPO", "").strip()
    )
    if repo:
        repo_path = Path(repo).expanduser()
        return (repo_path if repo_path.is_absolute() else root_path / repo_path).resolve()
    registry_path = resolve_report_intelligence_registry_dir(root_path, registry_dir)
    for candidate in (registry_path, *registry_path.parents):
        if (candidate / PRIVATE_REGISTRY_MANIFEST_NAME).is_file():
            return candidate
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
    removed: list[Path] = []
    blockers: list[str] = []

    if source_repo == output_path:
        blockers.append("private registry source and output repo must differ")
        return {
            "accepted": False,
            "root": str(root_path),
            "source_repo": str(source_repo),
            "output_dir": str(output_path),
            "registry_dir": str(registry_path),
            "copied_file_count": 0,
            "copied_files": [],
            "removed_file_count": 0,
            "removed_files": [],
            "manifest": {},
            "blockers": blockers,
            "blocker_count": len(blockers),
        }
    if registry_path.exists():
        write_report_fingerprint_manifest(registry_path)
    for relative in _managed_private_registry_paths():
        source = source_repo / relative
        target = output_path / relative
        if not source.exists() or not source.is_file():
            if target.is_file():
                target.unlink()
                removed.append(target)
            continue
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
        "removed_file_count": len(removed),
        "removed_files": [path.relative_to(output_path).as_posix() for path in removed],
        "manifest": manifest,
        "blockers": blockers,
        "blocker_count": len(blockers),
    }


def hydrate_private_registries(
    *,
    root: str | Path = ".",
    source_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Restore a validated published snapshot into the local ignored staging tree."""
    root_path = Path(root).expanduser().resolve()
    raw_source = str(source_dir or "").strip() or os.environ.get(
        "MOSAIC_REGISTRIES_REPO", ""
    ).strip()
    blockers: list[str] = []
    if not raw_source:
        blockers.append("private registry source repo not configured")
        return {
            "accepted": False,
            "root": str(root_path),
            "source_dir": "",
            "copied_file_count": 0,
            "copied_files": [],
            "removed_file_count": 0,
            "removed_files": [],
            "blockers": blockers,
            "blocker_count": len(blockers),
        }
    source_path = Path(raw_source).expanduser()
    if not source_path.is_absolute():
        source_path = root_path / source_path
    source_path = source_path.resolve()
    if source_path == root_path:
        blockers.append("private registry source repo and staging root must differ")
    source_registry = source_path / DEFAULT_REPORT_INTELLIGENCE_REGISTRY_DIR
    if not blockers:
        preflight = registries_preflight(
            root=root_path,
            registry_dir=source_registry,
        )
        blockers.extend(str(item) for item in preflight["blockers"])
    if blockers:
        return {
            "accepted": False,
            "root": str(root_path),
            "source_dir": str(source_path),
            "copied_file_count": 0,
            "copied_files": [],
            "removed_file_count": 0,
            "removed_files": [],
            "blockers": blockers,
            "blocker_count": len(blockers),
        }

    copied: list[Path] = []
    removed: list[Path] = []
    for relative in _managed_private_registry_paths():
        source = source_path / relative
        target = root_path / relative
        if not source.is_file():
            if target.is_file():
                target.unlink()
                removed.append(target)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(target)
    return {
        "accepted": True,
        "root": str(root_path),
        "source_dir": str(source_path),
        "copied_file_count": len(copied),
        "copied_files": [path.relative_to(root_path).as_posix() for path in copied],
        "removed_file_count": len(removed),
        "removed_files": [path.relative_to(root_path).as_posix() for path in removed],
        "blockers": [],
        "blocker_count": 0,
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


def _private_registry_manifest_blockers(
    repo_path: Path,
    manifest_path: Path,
    *,
    required_paths: Sequence[str] = (),
) -> list[str]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"registry_manifest.json unreadable: {exc}"]
    if not isinstance(manifest, Mapping):
        return ["registry_manifest.json must be an object"]
    blockers: list[str] = []
    if manifest.get("schema_version") != "mosaic_private_registries_manifest_v1":
        blockers.append("registry_manifest.json schema_version invalid")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        blockers.append("registry_manifest.json files missing")
        return blockers
    seen_paths: set[str] = set()
    vintage_input: list[dict[str, Any]] = []
    for index, raw_row in enumerate(files, 1):
        if not isinstance(raw_row, Mapping):
            blockers.append(f"registry_manifest.json files[{index}] must be an object")
            continue
        relative = str(raw_row.get("path") or "").strip()
        relative_path = Path(relative)
        if (
            not relative
            or relative_path.is_absolute()
            or any(part in {"", ".", ".."} for part in relative_path.parts)
        ):
            blockers.append(f"registry_manifest.json files[{index}].path invalid")
            continue
        if relative in seen_paths:
            blockers.append(f"registry_manifest.json duplicate path: {relative}")
            continue
        seen_paths.add(relative)
        path = repo_path / relative_path
        if not path.is_file():
            blockers.append(f"registry manifest file missing: {relative}")
            continue
        actual_hash = _sha256_file(path)
        if raw_row.get("sha256") != actual_hash:
            blockers.append(f"registry manifest hash mismatch: {relative}")
        if raw_row.get("bytes") != path.stat().st_size:
            blockers.append(f"registry manifest byte count mismatch: {relative}")
        vintage_input.append(
            {
                "path": relative,
                "sha256": actual_hash,
                "row_count": int(raw_row.get("row_count") or 0),
            }
        )
    if manifest.get("file_count") != len(files):
        blockers.append("registry_manifest.json file_count mismatch")
    registry_root = repo_path / "registry"
    actual_registry_paths = (
        {
            path.relative_to(repo_path).as_posix()
            for path in registry_root.rglob("*")
            if path.is_file() and path.suffix in PRIVATE_REGISTRY_JSON_SUFFIXES
        }
        if registry_root.is_dir()
        else set()
    )
    for relative in sorted(actual_registry_paths - seen_paths):
        blockers.append(f"registry JSON file missing from manifest: {relative}")
    for required_path in required_paths:
        if required_path not in seen_paths:
            blockers.append(
                f"registry manifest required path missing: {required_path}"
            )
    if manifest.get("data_vintage_hash") != _stable_hash(vintage_input):
        blockers.append("registry_manifest.json data_vintage_hash mismatch")
    return blockers


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
    blockers.extend(f"required registry file missing: {path}" for path in missing_files)
    if manifest_path.exists():
        try:
            registry_relative = registry_path.relative_to(repo_path)
        except ValueError:
            registry_relative = Path(DEFAULT_REPORT_INTELLIGENCE_REGISTRY_DIR)
        blockers.extend(
            _private_registry_manifest_blockers(
                repo_path,
                manifest_path,
                required_paths=tuple(
                    (registry_relative / path).as_posix()
                    for path in (
                        "report_metadata.jsonl",
                        "forecast_claims.jsonl",
                        "analytical_footprints.jsonl",
                        "processing_status.jsonl",
                        FINGERPRINT_MANIFEST_NAME,
                    )
                ),
            )
        )
    try:
        rows = _read_jsonl(fingerprint_path)
    except (OSError, json.JSONDecodeError) as exc:
        rows = []
        blockers.append(f"report fingerprint manifest unreadable: {exc}")
    duplicate_count = (
        _duplicate_count(rows, "source_id")
        + _duplicate_count(rows, "report_id")
        + _duplicate_count(rows, "source_hash")
    )
    if duplicate_count:
        blockers.append(
            f"duplicate report fingerprints detected: {duplicate_count}"
        )
    git_revision = (
        _git_output(repo_path, "rev-parse", "HEAD") if repo_path.exists() else ""
    )
    dirty = bool(
        _git_output(repo_path, "status", "--porcelain")
    ) if repo_path.exists() else False
    if repo_path.exists() and not git_revision:
        blockers.append("registries repo git revision missing")
    if dirty:
        blockers.append("registries repo dirty")
    return {
        "accepted": not blockers,
        "repo_path": str(repo_path),
        "registry_dir": str(registry_path),
        "git_revision": git_revision,
        "dirty": dirty,
        "dirty_blocker": "registries repo dirty" if dirty else "",
        "manifest_path": str(manifest_path),
        "manifest_hash": _sha256_file(manifest_path) if manifest_path.exists() else "",
        "fingerprint_manifest_path": str(fingerprint_path),
        "missing_file_count": len(missing_files),
        "missing_files": missing_files,
        "duplicate_fingerprint_count": duplicate_count,
        "blockers": blockers,
        "blocker_count": len(blockers),
    }
