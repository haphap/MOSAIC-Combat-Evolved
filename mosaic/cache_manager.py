"""Unified cache management for MOSAIC."""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any


class CacheManager:
    CATEGORIES = ("api", "signals", "snapshots", "checkpoints")
    _EXCLUDED_API_SUBDIRS: frozenset[str] = frozenset({"shared_snapshots", "checkpoints"})

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._api_cache_dir: Path = Path(config["data_cache_dir"])
        self._signal_cache_dir: Path = Path(config["results_dir"]) / "backtest_cache"
        self._snapshot_cache_dir: Path = Path(config["data_cache_dir"]) / "shared_snapshots"
        self._checkpoint_dir: Path = Path(config["data_cache_dir"]) / "checkpoints"

    def stats(self) -> dict[str, Any]:
        api_count, api_mb = self._dir_stats(self._api_cache_dir, exclude_subdirs=self._EXCLUDED_API_SUBDIRS)
        api_subdirs = sorted(
            p.name for p in self._api_cache_dir.iterdir()
            if p.is_dir() and p.name not in self._EXCLUDED_API_SUBDIRS
        ) if self._api_cache_dir.is_dir() else []

        sig_count, sig_mb = self._dir_stats(self._signal_cache_dir)

        snap_count, snap_mb = self._dir_stats(self._snapshot_cache_dir)
        snap_kinds = sorted(p.name for p in self._snapshot_cache_dir.iterdir() if p.is_dir()) if self._snapshot_cache_dir.is_dir() else []

        cp_count, cp_mb = self._dir_stats(self._checkpoint_dir)
        cp_tickers = sorted(p.stem for p in self._checkpoint_dir.glob("*.db")) if self._checkpoint_dir.is_dir() else []

        total_mb = api_mb + sig_mb + snap_mb + cp_mb

        return {
            "api": {"count": api_count, "size_mb": round(api_mb, 2), "subdirs": api_subdirs},
            "signals": {"count": sig_count, "size_mb": round(sig_mb, 2)},
            "snapshots": {"count": snap_count, "size_mb": round(snap_mb, 2), "kinds": snap_kinds},
            "checkpoints": {"count": cp_count, "size_mb": round(cp_mb, 2), "tickers": cp_tickers},
            "total_mb": round(total_mb, 2),
        }

    def cleanup(self, days: int, category: str = "all") -> dict[str, Any]:
        if days < 0:
            raise ValueError(f"days must be >= 0, got {days}")
        categories = self.CATEGORIES if category == "all" else (category,)
        by_category: dict[str, dict[str, Any]] = {}
        total_deleted = 0
        total_freed_mb = 0.0

        for cat in categories:
            if cat == "api":
                deleted, freed = self._cleanup_dir(self._api_cache_dir, days, exclude_subdirs=self._EXCLUDED_API_SUBDIRS)
            elif cat == "signals":
                deleted, freed = self._cleanup_dir(self._signal_cache_dir, days)
            elif cat == "snapshots":
                deleted, freed = self._cleanup_dir(self._snapshot_cache_dir, days)
            elif cat == "checkpoints":
                deleted, freed = self._cleanup_dir(self._checkpoint_dir, days)
            else:
                continue
            by_category[cat] = {"deleted_files": deleted, "freed_mb": round(freed, 2)}
            total_deleted += deleted
            total_freed_mb += freed

        return {
            "deleted_files": total_deleted,
            "freed_mb": round(total_freed_mb, 2),
            "by_category": by_category,
        }

    def clear(self, category: str) -> dict[str, Any]:
        if category == "all":
            total_deleted = 0
            total_freed_mb = 0.0
            for cat in self.CATEGORIES:
                result = self.clear(cat)
                total_deleted += result["deleted_files"]
                total_freed_mb += result["freed_mb"]
            return {"deleted_files": total_deleted, "freed_mb": round(total_freed_mb, 2)}

        if category == "checkpoints":
            try:
                from mosaic.graph.checkpointer import clear_all_checkpoints
            except ImportError:
                # mosaic.graph lands in Phase 2; until then fall back to a
                # plain rmtree of the checkpoint dir so cache.clear is still
                # operationally useful.
                count, size_mb = self._dir_stats(self._checkpoint_dir)
                if self._checkpoint_dir.is_dir():
                    shutil.rmtree(self._checkpoint_dir)
                return {"deleted_files": count, "freed_mb": round(size_mb, 2)}
            deleted = clear_all_checkpoints(self._config["data_cache_dir"])
            return {"deleted_files": deleted, "freed_mb": 0.0}

        if category == "signals":
            count, size_mb = self._dir_stats(self._signal_cache_dir)
            if self._signal_cache_dir.is_dir():
                shutil.rmtree(self._signal_cache_dir)
            return {"deleted_files": count, "freed_mb": round(size_mb, 2)}

        if category == "snapshots":
            count, size_mb = self._dir_stats(self._snapshot_cache_dir)
            if self._snapshot_cache_dir.is_dir():
                shutil.rmtree(self._snapshot_cache_dir)
            return {"deleted_files": count, "freed_mb": round(size_mb, 2)}

        if category == "api":
            count, size_mb = self._dir_stats(self._api_cache_dir, exclude_subdirs=self._EXCLUDED_API_SUBDIRS)
            if self._api_cache_dir.is_dir():
                for entry in list(self._api_cache_dir.iterdir()):
                    if entry.is_dir() and entry.name in self._EXCLUDED_API_SUBDIRS:
                        continue
                    if entry.is_dir():
                        shutil.rmtree(entry)
                    else:
                        entry.unlink()
            return {"deleted_files": count, "freed_mb": round(size_mb, 2)}

        return {"deleted_files": 0, "freed_mb": 0.0}

    def details(self, category: str, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        if category == "api":
            paths = list(self._walk_dir(self._api_cache_dir, exclude_subdirs=self._EXCLUDED_API_SUBDIRS))
        elif category == "signals":
            paths = list(self._walk_dir(self._signal_cache_dir))
        elif category == "snapshots":
            paths = list(self._walk_dir(self._snapshot_cache_dir))
        elif category == "checkpoints":
            paths = list(self._walk_dir(self._checkpoint_dir))
        else:
            paths = []

        timed_paths: list[tuple[float, Path]] = []
        for p in paths:
            try:
                timed_paths.append((p.stat().st_mtime, p))
            except OSError:
                continue

        entries = []
        for _, p in sorted(timed_paths, key=lambda x: x[0], reverse=True):
            try:
                st = p.stat()
                entries.append({
                    "path": str(p),
                    "size_kb": round(st.st_size / 1024, 2),
                    "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
                })
            except OSError:
                continue

        total = len(entries)
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "total": total,
            "page": page,
            "entries": entries[start:end],
        }

    def _walk_dir(self, root: Path, pattern: str = "*", exclude_subdirs: set[str] | None = None) -> list[Path]:
        if not root.is_dir():
            return []
        results: list[Path] = []
        for entry in root.rglob(pattern):
            if exclude_subdirs:
                parts = entry.relative_to(root).parts
                if any(part in exclude_subdirs for part in parts):
                    continue
            if entry.is_file():
                results.append(entry)
        return results

    def _dir_stats(self, root: Path, exclude_subdirs: set[str] | None = None) -> tuple[int, float]:
        if not root.is_dir():
            return 0, 0.0
        files = self._walk_dir(root, exclude_subdirs=exclude_subdirs)
        total_bytes = 0
        count = 0
        for f in files:
            try:
                total_bytes += f.stat().st_size
                count += 1
            except OSError:
                continue
        return count, total_bytes / (1024 * 1024)

    def _cleanup_dir(self, root: Path, days: int, exclude_subdirs: set[str] | None = None) -> tuple[int, float]:
        if not root.is_dir():
            return 0, 0.0
        if days == 0:
            count, size_mb = self._dir_stats(root, exclude_subdirs=exclude_subdirs)
            if exclude_subdirs:
                for entry in list(root.iterdir()):
                    if entry.is_dir() and entry.name in exclude_subdirs:
                        continue
                    if entry.is_dir():
                        shutil.rmtree(entry)
                    else:
                        try:
                            entry.unlink()
                        except OSError:
                            pass
            else:
                shutil.rmtree(root)
                root.mkdir(parents=True, exist_ok=True)
            return count, size_mb

        cutoff = time.time() - days * 86400
        deleted = 0
        freed_bytes = 0
        for f in self._walk_dir(root, exclude_subdirs=exclude_subdirs):
            try:
                if f.stat().st_mtime < cutoff:
                    freed_bytes += f.stat().st_size
                    f.unlink()
                    deleted += 1
            except OSError:
                continue
        return deleted, freed_bytes / (1024 * 1024)
