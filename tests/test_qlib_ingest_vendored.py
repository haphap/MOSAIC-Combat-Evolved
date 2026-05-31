"""Deps-light tests for the vendored collector discovery (Request #2).

Verifies find_qlib_collector resolves to the in-repo vendored collector.py for
both stock and ETF, without importing the collectors or running any ingest
(those need tushare/pyqlib/loguru + a TUSHARE_TOKEN, not present in CI).
"""

from __future__ import annotations

from pathlib import Path

from mosaic.dataflows import qlib_ingest


def _vendored_root() -> Path:
    return Path(qlib_ingest.__file__).resolve().parent / "collectors" / "data_collector"


def test_stock_collector_resolves_to_vendored(monkeypatch):
    monkeypatch.delenv("MOSAIC_QLIB_REPO", raising=False)
    paths = qlib_ingest.find_qlib_collector("stock")
    assert paths.collector_script == _vendored_root() / "tushare" / "collector.py"
    assert paths.collector_script.is_file()


def test_etf_collector_resolves_to_vendored(monkeypatch):
    monkeypatch.delenv("MOSAIC_QLIB_ETF_COLLECTOR", raising=False)
    monkeypatch.delenv("MOSAIC_QLIB_REPO", raising=False)
    paths = qlib_ingest.find_qlib_collector("etf")
    assert paths.collector_script == _vendored_root() / "tushare_etf" / "collector.py"
    assert paths.collector_script.is_file()


def test_env_override_wins_over_vendored(monkeypatch, tmp_path):
    # An explicit MOSAIC_QLIB_REPO with a valid collector must take precedence.
    fake_repo = tmp_path / "qlib"
    col = fake_repo / "scripts" / "data_collector" / "tushare" / "collector.py"
    col.parent.mkdir(parents=True)
    col.write_text("# fake\n", encoding="utf-8")
    monkeypatch.setenv("MOSAIC_QLIB_REPO", str(fake_repo))
    paths = qlib_ingest.find_qlib_collector("stock")
    assert paths.collector_script == col.resolve()


def test_vendored_layout_self_contained():
    """The vendored dir ships dump_bin + data_collector base/utils + both collectors."""
    root = _vendored_root()
    assert (root.parent / "dump_bin.py").is_file()
    assert (root / "base.py").is_file()
    assert (root / "utils.py").is_file()
    assert (root / "tushare" / "collector.py").is_file()
    assert (root / "tushare_etf" / "collector.py").is_file()
    # Provenance/licensing present.
    assert (root.parent / "NOTICE.md").is_file()
    assert (root.parent / "LICENSE.qlib").is_file()


def test_vendored_dirs_are_packages():
    """collectors/ and data_collector/ carry __init__.py so the tree ships in a
    built wheel/sdist (setuptools.packages.find only discovers real packages)."""
    root = _vendored_root()
    assert (root.parent / "__init__.py").is_file()
    assert (root / "__init__.py").is_file()
    assert (root / "tushare" / "__init__.py").is_file()
    assert (root / "tushare_etf" / "__init__.py").is_file()
