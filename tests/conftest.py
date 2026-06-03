"""Test isolation for env vars that point at real external resources.

``mosaic/__init__`` calls ``load_dotenv()``, so a developer's ``.env`` bleeds
into the test process. Vars like ``MOSAIC_PRIVATE_PROMPT_REPO`` /
``MOSAIC_MIROFISH_URL`` would otherwise make tests operate on a real prompt repo
or MiroFish service. Clear them before each test; tests that need them set them
explicitly via ``monkeypatch.setenv`` (which runs after this autouse fixture).
"""

from __future__ import annotations

import pytest

_LEAK_VARS = (
    "MOSAIC_PRIVATE_PROMPT_REPO",
    "MOSAIC_PRIVATE_PROMPT_REPO_ID",
    "MOSAIC_MIROFISH_URL",
)


@pytest.fixture(autouse=True)
def _isolate_external_env(monkeypatch):
    for var in _LEAK_VARS:
        monkeypatch.delenv(var, raising=False)
