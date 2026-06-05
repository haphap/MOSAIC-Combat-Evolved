"""Test isolation for env vars that point at real external resources.

``mosaic/__init__`` calls ``load_dotenv()``, so a developer's ``.env`` bleeds
into the test process. Vars like ``MOSAIC_PROMPTS_REPO`` /
``MOSAIC_MIROFISH_URL`` would otherwise make tests operate on a real prompt repo
or MiroFish service. Clear them before each test; tests that need them set them
explicitly via ``monkeypatch.setenv`` (which runs after this autouse fixture).
"""

from __future__ import annotations

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


@pytest.fixture(autouse=True)
def _isolate_external_env(monkeypatch):
    for var in _LEAK_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MOSAIC_CHINA_POLICY_DB_AUTO_SYNC", "0")
