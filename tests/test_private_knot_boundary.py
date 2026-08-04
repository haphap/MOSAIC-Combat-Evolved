from __future__ import annotations

import json

import pytest

from scripts import check_private_knot_boundary


def test_public_boundary_uses_knot_free_runtime_v5(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOSAIC_PROMPTS_REPO", raising=False)
    monkeypatch.delenv("MOSAIC_PRIVATE_PROMPT_REPO", raising=False)

    check_private_knot_boundary.check(require_private=False)

    runtime = json.loads(
        check_private_knot_boundary.RUNTIME_AGENT_MANIFEST_PATH.read_text(
            encoding="utf-8"
        )
    )
    assert runtime["schema_version"] == "runtime_agent_manifest_v5"
    assert "knot" not in json.dumps(runtime).lower()


def test_private_boundary_fails_closed_without_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MOSAIC_PROMPTS_REPO", raising=False)
    monkeypatch.delenv("MOSAIC_PRIVATE_PROMPT_REPO", raising=False)

    with pytest.raises(ValueError, match="private Prompt repository is required"):
        check_private_knot_boundary.check(require_private=True)
