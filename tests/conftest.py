"""Test isolation for env vars that point at real external resources.

``mosaic/__init__`` calls ``load_dotenv()``, so a developer's ``.env`` bleeds
into the test process. Vars like ``MOSAIC_PROMPTS_REPO`` /
``MOSAIC_MIROFISH_URL`` would otherwise make tests operate on a real prompt repo
or MiroFish service. Clear them before each test; tests that need them set them
explicitly via ``monkeypatch.setenv`` (which runs after this autouse fixture).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

_LEAK_VARS = (
    "MOSAIC_PROMPTS_REPO",
    "MOSAIC_PROMPTS_ROOT",
    "MOSAIC_PROMPTS_REPO_ID",
    "MOSAIC_PRIVATE_PROMPT_REPO",
    "MOSAIC_PRIVATE_PROMPT_REPO_ID",
    "MOSAIC_MIROFISH_URL",
    "MOSAIC_CHINA_POLICY_DB_DIR",
    "MOSAIC_CHINA_POLICY_DB_REPO_URL",
    "MOSAIC_CHINA_POLICY_DB_RAW_BASE_URL",
    "MOSAIC_CHINA_POLICY_DB_PUSH_UPDATES",
)

_RKE_MANUAL_REVIEW_SCRATCH = frozenset(
    {
        "gold_set_reviewed.jsonl",
        "gold_set_full_reviewed.jsonl",
        "source_license_policy_reviewed.json",
        "source_license_policy_import.jsonl",
        "lockbox_reviewed.json",
    }
)


@pytest.fixture(autouse=True)
def _isolate_external_env(monkeypatch):
    for var in _LEAK_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MOSAIC_CHINA_POLICY_DB_AUTO_SYNC", "0")


@pytest.fixture(autouse=True)
def _ignore_rke_manual_review_scratch_in_registry_copies(monkeypatch):
    """Keep local reviewer scratch files out of copied registry fixtures."""

    original_copytree = shutil.copytree
    project_registry_path = (Path.cwd() / "registry").resolve()

    def copytree_without_review_scratch(
        src,
        dst,
        symlinks=False,
        ignore=None,
        copy_function=shutil.copy2,
        ignore_dangling_symlinks=False,
        dirs_exist_ok=False,
    ):
        effective_ignore = ignore
        src_path = Path(src).resolve()
        dst_parts = Path(dst).parts
        should_ignore_review_scratch = src_path == project_registry_path and any(
            part.startswith("pytest-") for part in dst_parts
        )
        if should_ignore_review_scratch:
            original_ignore = ignore

            def ignore_review_scratch(dirname, names):
                ignored = set(original_ignore(dirname, names)) if original_ignore else set()
                ignored.update(name for name in names if name in _RKE_MANUAL_REVIEW_SCRATCH)
                return ignored

            effective_ignore = ignore_review_scratch

        return original_copytree(
            src,
            dst,
            symlinks=symlinks,
            ignore=effective_ignore,
            copy_function=copy_function,
            ignore_dangling_symlinks=ignore_dangling_symlinks,
            dirs_exist_ok=dirs_exist_ok,
        )

    monkeypatch.setattr("shutil.copytree", copytree_without_review_scratch)
