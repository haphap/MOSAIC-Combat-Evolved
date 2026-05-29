"""Tests for mosaic.dataflows.sino_us (Plan §5.1 geopolitical)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mosaic.dataflows import sino_us
from mosaic.dataflows.exceptions import DataVendorUnavailable

_CSV = (
    "年份,1月,2月,3月,4月,5月,6月,7月,8月,9月,10月,11月,12月\n"
    "2022,-7.0,-7.1,-7.2,-7.3,-7.4,-7.5,-7.6,-7.7,-7.8,-7.9,-8.0,-8.1\n"
    "2023,-6.0,-6.1,-6.2,-6.3,-6.4,-6.5,-6.6,-6.7,-6.8,-6.9,-7.0,-7.1\n"
    "2024,-5.0,-5.1,-5.2,,,,,,,,,\n"
)


@pytest.fixture
def csv_env(tmp_path: Path, monkeypatch):
    p = tmp_path / "sino.csv"
    p.write_text(_CSV, encoding="utf-8")
    monkeypatch.setenv("MOSAIC_SINO_US_CSV", str(p))
    return p


def test_windowed_series_and_trend(csv_env):
    out = sino_us.get_us_china_relations("2023-12-31", look_back_days=365)
    assert "Sino-US Relations Index" in out
    assert "2023-01,-6.0" in out
    assert "2023-12,-7.1" in out
    # 2022 rows are outside the 365-day window.
    assert "2022-01" not in out
    # trend: -7.1 - (-6.0) = -1.1 → tension worsening.
    assert "tension" in out


def test_blank_cells_skipped(csv_env):
    out = sino_us.get_us_china_relations("2024-12-31", look_back_days=365)
    assert "2024-03,-5.2" in out
    assert "2024-04" not in out  # blank cell


def test_no_data_in_window_returns_note(csv_env):
    out = sino_us.get_us_china_relations("2019-12-31", look_back_days=30)
    assert "No relations-index data in window" in out


def test_bad_date_raises(csv_env):
    with pytest.raises(DataVendorUnavailable, match="YYYY-MM-DD"):
        sino_us.get_us_china_relations("2024/01/01")


def test_missing_csv_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("MOSAIC_SINO_US_CSV", str(tmp_path / "nope.csv"))
    with pytest.raises(DataVendorUnavailable, match="not readable"):
        sino_us.get_us_china_relations("2024-06-30")
