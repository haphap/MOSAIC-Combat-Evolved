"""Integrity-checked loader boundary for private KNOT modules."""

from __future__ import annotations

import hashlib
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
import re
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any


_PUBLIC_ROOT = Path(__file__).resolve().parents[2]
_PUBLIC_REF_PATH = (
    _PUBLIC_ROOT
    / "registry"
    / "prompt_checks"
    / "knot_runtime_contract_ref_v2.json"
)
_PRIVATE_MANIFEST_RELATIVE_PATH = Path(
    "registry/knot/private_runtime_manifest_v1.json"
)
_MODULE_LOCK = threading.Lock()
_MODULES: dict[str, ModuleType] = {}
_INSERTED_RUNTIME_ROOTS: set[str] = set()
_PRIVATE_SOURCE_FINDER: _VerifiedPrivateSourceFinder | None = None


class _VerifiedPrivateSourceLoader(importlib.abc.Loader):
    def __init__(self, path: Path, expected_hash: str) -> None:
        self._path = path
        self._expected_hash = expected_hash

    def create_module(self, spec: Any) -> ModuleType | None:
        return None

    def exec_module(self, module: ModuleType) -> None:
        try:
            source = self._path.read_bytes()
        except OSError as exc:
            raise RuntimeError("private KNOT runtime module is unavailable") from exc
        if _sha256_bytes(source) != self._expected_hash:
            raise RuntimeError("private KNOT runtime integrity check failed")
        code = compile(source, str(self._path), "exec", dont_inherit=True)
        exec(code, module.__dict__)


class _VerifiedPrivateSourceFinder(importlib.abc.MetaPathFinder):
    def __init__(
        self,
        entries: dict[str, tuple[Path, str, bool]],
    ) -> None:
        self._entries = entries

    def find_spec(
        self,
        fullname: str,
        path: Any = None,
        target: ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        del path, target
        if fullname != "mosaic_knot" and not fullname.startswith("mosaic_knot."):
            return None
        entry = self._entries.get(fullname)
        if entry is None:
            raise ModuleNotFoundError(
                f"unregistered private KNOT module import: {fullname}"
            )
        module_path, expected_hash, is_package = entry
        loader = _VerifiedPrivateSourceLoader(module_path, expected_hash)
        return importlib.util.spec_from_file_location(
            fullname,
            module_path,
            loader=loader,
            submodule_search_locations=(
                [str(module_path.parent)] if is_package else None
            ),
        )


def private_repo_root() -> Path:
    configured = (
        os.environ.get("MOSAIC_KNOT_RUNTIME_ROOT")
        or os.environ.get("MOSAIC_PROMPTS_REPO")
        or os.environ.get("MOSAIC_PRIVATE_PROMPT_REPO")
    )
    if not configured:
        raise RuntimeError("private KNOT runtime is not configured")
    root = Path(configured).expanduser().resolve()
    if root.name == "mosaic" and root.parent.name == "prompts":
        root = root.parents[1]
    return root


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _private_runtime_manifest() -> dict[str, Any]:
    try:
        public_ref = json.loads(_PUBLIC_REF_PATH.read_text(encoding="utf-8"))
        expected_manifest_hash = public_ref["private_runtime_manifest_hash"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("public KNOT runtime reference is invalid") from exc
    manifest_path = private_repo_root() / _PRIVATE_MANIFEST_RELATIVE_PATH
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("private KNOT runtime manifest is unavailable") from exc
    if _sha256_bytes(manifest_bytes) != expected_manifest_hash:
        raise RuntimeError("private KNOT runtime manifest integrity check failed")
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "private_knot_runtime_manifest_v1"
        or not isinstance(manifest.get("files"), dict)
    ):
        raise RuntimeError("private KNOT runtime manifest is invalid")
    return manifest


def load_private_knot_module(logical_name: str, module_name: str) -> ModuleType:
    cached = _MODULES.get(logical_name)
    if cached is not None:
        return cached
    with _MODULE_LOCK:
        cached = _MODULES.get(logical_name)
        if cached is not None:
            return cached
        manifest = _private_runtime_manifest()
        root = private_repo_root()
        _verify_manifest_files(manifest, root)
        module_path = _verified_manifest_file(manifest, logical_name, root)
        source_entries = _verify_private_python_package(manifest, root)
        _install_private_source_finder(source_entries)
        runtime_python_root = root / "runtime" / "python"
        runtime_python_root_text = str(runtime_python_root)
        if runtime_python_root_text not in sys.path:
            sys.path.insert(0, runtime_python_root_text)
            _INSERTED_RUNTIME_ROOTS.add(runtime_python_root_text)
        _purge_private_package_modules()
        importlib.invalidate_caches()
        try:
            module = importlib.import_module(module_name)
        except Exception:
            _purge_private_package_modules()
            _remove_private_source_finder()
            raise
        imported_path = Path(module.__file__ or "").resolve()
        if imported_path != module_path:
            _purge_private_package_modules()
            raise RuntimeError("private KNOT runtime imported from an unpinned path")
        _MODULES[logical_name] = module
        return module


def clear_private_knot_runtime_cache() -> None:
    with _MODULE_LOCK:
        _MODULES.clear()
        _purge_private_package_modules()
        _remove_private_source_finder()
        for runtime_root in tuple(_INSERTED_RUNTIME_ROOTS):
            while runtime_root in sys.path:
                sys.path.remove(runtime_root)
        _INSERTED_RUNTIME_ROOTS.clear()
        importlib.invalidate_caches()


def _purge_private_package_modules() -> None:
    for module_name in tuple(sys.modules):
        if module_name == "mosaic_knot" or module_name.startswith("mosaic_knot."):
            sys.modules.pop(module_name, None)


def _verify_manifest_files(manifest: dict[str, Any], root: Path) -> None:
    """Verify every file in the pinned runtime closure before importing code."""
    paths: set[Path] = set()
    for logical_name in manifest["files"]:
        path = _verified_manifest_file(manifest, logical_name, root)
        if path in paths:
            raise RuntimeError("private KNOT runtime manifest has duplicate paths")
        paths.add(path)


def _verified_manifest_file(
    manifest: dict[str, Any], logical_name: str, root: Path
) -> Path:
    entry = manifest["files"].get(logical_name)
    if not isinstance(entry, dict):
        raise RuntimeError("private KNOT runtime module is not registered")
    relative_path = entry.get("relative_path")
    expected_hash = entry.get("sha256")
    if not isinstance(relative_path, str) or not isinstance(expected_hash, str):
        raise RuntimeError("private KNOT runtime module reference is invalid")
    unresolved_path = root / relative_path
    _reject_symlink_path(unresolved_path, root)
    module_path = unresolved_path.resolve()
    if not module_path.is_relative_to(root):
        raise RuntimeError("private KNOT runtime module escaped its repository")
    if not module_path.is_file():
        raise RuntimeError("private KNOT runtime module is unavailable")
    try:
        module_bytes = module_path.read_bytes()
    except OSError as exc:
        raise RuntimeError("private KNOT runtime module is unavailable") from exc
    if _sha256_bytes(module_bytes) != expected_hash:
        raise RuntimeError("private KNOT runtime integrity check failed")
    return module_path


def _verify_private_python_package(
    manifest: dict[str, Any], root: Path
) -> dict[str, tuple[Path, str, bool]]:
    """Close the package over registered source and bypass all bytecode loaders."""
    unresolved_package_root = root / "runtime" / "python" / "mosaic_knot"
    _reject_symlink_path(unresolved_package_root, root)
    package_root = unresolved_package_root.resolve()
    if not package_root.is_relative_to(root) or not package_root.is_dir():
        raise RuntimeError("private KNOT Python package is unavailable")
    registered: dict[Path, tuple[str, str]] = {}
    for logical_name, entry in manifest["files"].items():
        if not isinstance(entry, dict):
            continue
        relative_path = entry.get("relative_path")
        if not isinstance(relative_path, str) or not relative_path.endswith(".py"):
            continue
        candidate = (root / relative_path).resolve()
        if candidate.is_relative_to(package_root):
            if candidate.suffix != ".py":
                raise RuntimeError(
                    "private KNOT package contains a registered non-source module"
                )
            registered[candidate] = (logical_name, entry["sha256"])
    actual_sources: set[Path] = set()
    allowed_directories = {package_root}
    for source_path in registered:
        parent = source_path.parent
        while parent.is_relative_to(package_root):
            allowed_directories.add(parent)
            if parent == package_root:
                break
            parent = parent.parent
    for entry_path in package_root.rglob("*"):
        if entry_path.is_symlink():
            raise RuntimeError("private KNOT package contains a symlink")
        resolved = entry_path.resolve()
        if entry_path.is_dir():
            if entry_path.name == "__pycache__":
                if entry_path.parent.resolve() not in allowed_directories:
                    raise RuntimeError(
                        "private KNOT package contains an unregistered bytecode cache"
                    )
                continue
            if resolved not in allowed_directories:
                raise RuntimeError(
                    "private KNOT package contains an unregistered namespace"
                )
            continue
        if entry_path.suffix == ".py":
            actual_sources.add(resolved)
            continue
        if entry_path.suffix == ".pyc":
            if not _is_registered_bytecode_cache(entry_path, registered):
                raise RuntimeError(
                    "private KNOT package contains an unregistered importable file"
                )
            continue
        if any(
            entry_path.name.endswith(suffix)
            for suffix in importlib.machinery.EXTENSION_SUFFIXES
        ) or entry_path.suffix in {".pyd", ".so"}:
            raise RuntimeError(
                "private KNOT package contains an unregistered importable file"
            )
    if actual_sources != set(registered):
        raise RuntimeError("private KNOT Python package contains unregistered modules")
    for logical_name, _expected_hash in registered.values():
        _verified_manifest_file(manifest, logical_name, root)
    source_entries: dict[str, tuple[Path, str, bool]] = {}
    for source_path, (_logical_name, expected_hash) in registered.items():
        relative = source_path.relative_to(package_root)
        if source_path.name == "__init__.py":
            parts = relative.parent.parts
            module_name = ".".join(("mosaic_knot", *parts))
            is_package = True
        else:
            module_name = ".".join(
                ("mosaic_knot", *relative.with_suffix("").parts)
            )
            is_package = False
        if module_name in source_entries:
            raise RuntimeError("private KNOT package module identity collision")
        source_entries[module_name] = (source_path, expected_hash, is_package)
    if "mosaic_knot" not in source_entries:
        raise RuntimeError("private KNOT Python package initializer is missing")
    package_directories = {
        path.parent
        for name, (path, _digest, is_package) in source_entries.items()
        if is_package and name.startswith("mosaic_knot")
    }
    if package_directories != allowed_directories:
        raise RuntimeError("private KNOT package contains an unregistered namespace")
    return source_entries


def _reject_symlink_path(path: Path, root: Path) -> None:
    current = path
    while current != root:
        if current.is_symlink():
            raise RuntimeError("private KNOT runtime path contains a symlink")
        if root not in current.parents:
            raise RuntimeError("private KNOT runtime module escaped its repository")
        current = current.parent


def _is_registered_bytecode_cache(
    path: Path,
    registered: dict[Path, tuple[str, str]],
) -> bool:
    if path.parent.name != "__pycache__":
        source_path = path.with_suffix(".py").resolve()
        return source_path in registered
    source_parent = path.parent.parent.resolve()
    for source_path in registered:
        if source_path.parent != source_parent:
            continue
        stem = re.escape(source_path.stem)
        if re.fullmatch(rf"{stem}\.[A-Za-z0-9_.-]+\.pyc", path.name):
            return True
    return False


def _install_private_source_finder(
    entries: dict[str, tuple[Path, str, bool]],
) -> None:
    global _PRIVATE_SOURCE_FINDER
    _remove_private_source_finder()
    finder = _VerifiedPrivateSourceFinder(entries)
    sys.meta_path.insert(0, finder)
    _PRIVATE_SOURCE_FINDER = finder


def _remove_private_source_finder() -> None:
    global _PRIVATE_SOURCE_FINDER
    if _PRIVATE_SOURCE_FINDER is not None:
        while _PRIVATE_SOURCE_FINDER in sys.meta_path:
            sys.meta_path.remove(_PRIVATE_SOURCE_FINDER)
    _PRIVATE_SOURCE_FINDER = None
