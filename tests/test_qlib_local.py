"""Phase 3.5A sanity test: verify ``mosaic.dataflows.qlib_local`` can read a
synthetic mini qlib dataset built in a tmp dir.

Doesn't need the real ``~/.qlib/qlib_data/cn_data`` to exist — instead we
construct a 3-ticker × 30-day fake dataset in qlib's binary format from
scratch and point the ``QLIB_CN_DATA_PATH`` env at it.

If this passes, the read path is wired correctly for Phase 3.5B's bulk
ingest output.
"""

from __future__ import annotations

import importlib.util
import struct
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# qlib (pyqlib, the .[backtest] extra) is a heavy/optional dep; CI's Python lane
# doesn't install it, so qlib-requiring tests skip there rather than ERROR.
_HAS_QLIB = importlib.util.find_spec("qlib") is not None


def _write_mini_qlib_dataset(root: Path) -> None:
    """Build a 3-ticker × 30-trading-day qlib dataset rooted at ``root``."""
    # Calendar: 30 weekdays starting 2024-06-03 (Mon)
    calendars_dir = root / "calendars"
    calendars_dir.mkdir(parents=True, exist_ok=True)
    base = pd.Timestamp("2024-06-03")
    cal: list[str] = []
    cur = base
    while len(cal) < 30:
        if cur.weekday() < 5:
            cal.append(cur.strftime("%Y-%m-%d"))
        cur += pd.Timedelta(days=1)
    (calendars_dir / "day.txt").write_text("\n".join(cal) + "\n", encoding="utf-8")

    # Instruments — three fake tickers, each tradable for the full window.
    instruments_dir = root / "instruments"
    instruments_dir.mkdir(parents=True, exist_ok=True)
    instruments_lines = [
        f"sh000300\t{cal[0]}\t{cal[-1]}",  # benchmark
        f"sh600519\t{cal[0]}\t{cal[-1]}",  # 茅台
        f"sz000001\t{cal[0]}\t{cal[-1]}",  # 平安银行
    ]
    (instruments_dir / "all.txt").write_text(
        "\n".join(instruments_lines) + "\n", encoding="utf-8"
    )
    # CSI300 universe is just 600519 + 000300 for this test
    (instruments_dir / "csi300.txt").write_text(
        f"sh600519\t{cal[0]}\t{cal[-1]}\nsh000300\t{cal[0]}\t{cal[-1]}\n",
        encoding="utf-8",
    )

    # Features — qlib binary format: bytes 0-3 = float32 calendar start index,
    # bytes 4+ = float32 values one per trading day.
    features_dir = root / "features"
    features_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(seed=42)
    for ticker, base_price in [("sh000300", 3500), ("sh600519", 1500), ("sz000001", 12)]:
        ticker_dir = features_dir / ticker
        ticker_dir.mkdir(parents=True, exist_ok=True)
        # Random-walk close, OHLV derived
        closes = base_price * np.cumprod(1 + rng.normal(0, 0.01, size=30))
        opens = closes * (1 + rng.normal(0, 0.002, size=30))
        highs = np.maximum(closes, opens) * (1 + np.abs(rng.normal(0, 0.003, size=30)))
        lows = np.minimum(closes, opens) * (1 - np.abs(rng.normal(0, 0.003, size=30)))
        volumes = (np.full(30, 10_000_000) * (1 + rng.normal(0, 0.2, size=30))).astype(
            np.float32
        )
        factors = np.ones(30, dtype=np.float32)  # no splits in this test

        for feature_name, values in [
            ("open", opens.astype(np.float32)),
            ("high", highs.astype(np.float32)),
            ("low", lows.astype(np.float32)),
            ("close", closes.astype(np.float32)),
            ("volume", volumes),
            ("factor", factors),
        ]:
            file = ticker_dir / f"{feature_name}.day.bin"
            with open(file, "wb") as f:
                # Calendar start index 0 = first day in the calendar
                f.write(struct.pack("<f", 0.0))
                f.write(values.tobytes())


@pytest.fixture
def mini_qlib_dataset(tmp_path: Path, monkeypatch):
    """Spin up a 3-ticker × 30-day qlib dataset and point the env at it."""
    cn_data_root = tmp_path / "cn_data"
    _write_mini_qlib_dataset(cn_data_root)

    # Import qlib_local and reset its cached path (it caches on first call).
    monkeypatch.setenv("QLIB_CN_DATA_PATH", str(cn_data_root))
    import importlib

    import mosaic.dataflows.qlib_local as qlib_local

    importlib.reload(qlib_local)  # drop @lru_cache + module-level _cached_data_path
    yield cn_data_root


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_QLIB, reason="qlib not installed (.[backtest] extra)")
def test_pyqlib_imports():
    """Phase 3.5A entry test: pyqlib must be importable."""
    import qlib  # noqa: F401
    import qlib.data  # noqa: F401


def test_calendar_loaded(mini_qlib_dataset: Path):
    """Reader picks up the synthetic 30-weekday calendar."""
    from mosaic.dataflows.qlib_local import _load_calendar

    cal = _load_calendar()
    assert len(cal) == 30
    # First day is a Monday (we constructed it that way)
    assert cal[0].weekday() == 0


def test_data_path_resolution(mini_qlib_dataset: Path):
    """``_get_data_path`` follows the QLIB_CN_DATA_PATH env override."""
    from mosaic.dataflows.qlib_local import _get_data_path

    assert _get_data_path() == mini_qlib_dataset


def test_get_stock_returns_ohlcv_for_known_ticker(mini_qlib_dataset: Path):
    """End-to-end: ``get_stock`` reads our synthetic 600519.SH binary
    files and returns a string with OHLCV-like content."""
    from mosaic.dataflows.qlib_local import get_stock

    out = get_stock("600519.SH", "2024-06-03", "2024-07-12")
    assert isinstance(out, str)
    # Loose smoke: should mention the ticker or contain numeric content
    # (the formatter in qlib_local.py builds a markdown-ish summary).
    assert len(out) > 50
    # Should NOT be the "no data" sentinel
    assert "No stock data found" not in out


def test_unknown_ticker_raises_data_vendor_unavailable(mini_qlib_dataset: Path):
    """Tickers not in the synthetic dataset surface as DataVendorUnavailable
    (the contract that downstream agent code already handles)."""
    from mosaic.dataflows.exceptions import DataVendorUnavailable
    from mosaic.dataflows.qlib_local import get_stock

    with pytest.raises(DataVendorUnavailable, match="No qlib local data"):
        get_stock("999999.SH", "2024-06-03", "2024-07-12")


def test_missing_data_raises_when_path_unset(monkeypatch, tmp_path: Path):
    """If neither env nor any candidate path exists, reader degrades to
    ``DataVendorUnavailable``."""
    monkeypatch.delenv("QLIB_CN_DATA_PATH", raising=False)
    # Point candidate paths to a non-existent directory
    fake_home = tmp_path / "no_home"
    monkeypatch.setenv("HOME", str(fake_home))

    import importlib

    import mosaic.dataflows.qlib_local as qlib_local

    importlib.reload(qlib_local)

    from mosaic.dataflows.exceptions import DataVendorUnavailable

    with pytest.raises(DataVendorUnavailable, match="Qlib CN data not found"):
        qlib_local._get_data_path()
