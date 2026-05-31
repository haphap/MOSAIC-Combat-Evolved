"""Tests for ~/.mosaic/config.json persistence (TUI settings page support).

Each test points MOSAIC_CONFIG at a tmp file and reloads the config module so
_CONFIG_FILE picks up the override, keeping the suite hermetic.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def cfg_mod(tmp_path: Path, monkeypatch):
    """Reload mosaic.dataflows.config with MOSAIC_CONFIG → a tmp file."""
    cfg_file = tmp_path / "config.json"
    monkeypatch.setenv("MOSAIC_CONFIG", str(cfg_file))
    import mosaic.dataflows.config as config

    config = importlib.reload(config)
    yield config, cfg_file
    # Restore default module state for other tests.
    monkeypatch.delenv("MOSAIC_CONFIG", raising=False)
    importlib.reload(config)


def test_absent_file_uses_defaults(cfg_mod):
    config, cfg_file = cfg_mod
    assert not cfg_file.exists()
    config.initialize_config()
    live = config.get_config()
    # Unchanged from DEFAULT_CONFIG.
    assert live["llm_provider"] == "anthropic"
    assert live["output_language"] == "Chinese"


def test_save_writes_file_and_applies(cfg_mod):
    config, cfg_file = cfg_mod
    applied = config.save_config({"output_language": "English"})
    assert applied["output_language"] == "English"
    assert cfg_file.is_file()
    on_disk = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert on_disk["output_language"] == "English"
    # Active context reflects it immediately.
    assert config.get_config()["output_language"] == "English"


def test_persisted_file_loaded_at_init(cfg_mod):
    config, cfg_file = cfg_mod
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    cfg_file.write_text(json.dumps({"llm_provider": "deepseek"}), encoding="utf-8")
    config.initialize_config()
    live = config.get_config()
    assert live["llm_provider"] == "deepseek"
    # Other defaults still present (merge over defaults, not replace).
    assert live["output_language"] == "Chinese"


def test_invalid_file_falls_back_to_defaults(cfg_mod):
    config, cfg_file = cfg_mod
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    cfg_file.write_text("{ not valid json", encoding="utf-8")
    config.initialize_config()  # must not raise
    assert config.get_config()["llm_provider"] == "anthropic"
