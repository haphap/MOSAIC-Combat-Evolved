"""Tests for mosaic.dataflows.qlib_ingest (Plan §11.3 sub-step 3.5B)."""

from __future__ import annotations

import struct
import subprocess
from pathlib import Path

import pytest

from mosaic.dataflows import qlib_ingest


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestFindCollector:
    def test_env_override_wins(self, tmp_path: Path, monkeypatch):
        # Build a fake repo layout
        repo = tmp_path / "fake_qlib"
        (repo / "scripts" / "data_collector" / "tushare").mkdir(parents=True)
        (repo / "scripts" / "data_collector" / "tushare" / "collector.py").write_text(
            "# fake collector"
        )
        monkeypatch.setenv("MOSAIC_QLIB_REPO", str(repo))
        result = qlib_ingest.find_qlib_collector()
        assert result.repo_root == repo.resolve()
        assert result.collector_script == (
            repo / "scripts" / "data_collector" / "tushare" / "collector.py"
        ).resolve()

    def test_missing_everywhere_raises(self, tmp_path: Path, monkeypatch):
        # Point env at a non-existent dir; redirect HOME so candidates fail too.
        monkeypatch.setenv("MOSAIC_QLIB_REPO", str(tmp_path / "nope"))
        monkeypatch.setenv("HOME", str(tmp_path / "fake_home"))
        # Also make the relative ../qlib not exist by pointing cwd somewhere clean
        monkeypatch.chdir(tmp_path)

        with pytest.raises(qlib_ingest.CollectorNotFound, match="not found"):
            qlib_ingest.find_qlib_collector()

    def test_real_repo_found(self):
        """If a real qlib repo is on disk (this dev box has one), discovery
        succeeds — sanity check we won't break in real use."""
        try:
            result = qlib_ingest.find_qlib_collector()
        except qlib_ingest.CollectorNotFound:
            pytest.skip("no qlib repo on this machine; covered by other tests")
        assert result.collector_script.is_file()


class TestFindEtfCollector:
    def test_env_override_locates_etf_collector(self, tmp_path: Path, monkeypatch):
        coll = tmp_path / "tushare_etf" / "collector.py"
        coll.parent.mkdir(parents=True)
        coll.write_text("# fake etf collector")
        monkeypatch.setenv("MOSAIC_QLIB_ETF_COLLECTOR", str(coll))
        result = qlib_ingest.find_qlib_collector("etf")
        assert result.collector_script == coll
        assert result.repo_root == coll.parent

    def test_missing_etf_collector_raises(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("MOSAIC_QLIB_ETF_COLLECTOR", str(tmp_path / "nope.py"))
        monkeypatch.setenv("HOME", str(tmp_path / "fake_home"))
        monkeypatch.delenv("MOSAIC_QLIB_REPO", raising=False)
        with pytest.raises(qlib_ingest.CollectorNotFound, match="ETF collector not found"):
            qlib_ingest.find_qlib_collector("etf")

    def test_etf_default_data_dir_is_cn_etf(self):
        assert qlib_ingest.DEFAULT_QLIB_ETF_DATA_DIR.name == "cn_etf"
        assert qlib_ingest.DEFAULT_QLIB_DATA_DIR.name == "cn_data"


# ---------------------------------------------------------------------------
# Subprocess wrapper (mocked)
# ---------------------------------------------------------------------------


class TestRunCollector:
    def test_constructs_correct_command(self, tmp_path: Path, monkeypatch):
        repo = tmp_path / "fake_qlib"
        (repo / "scripts" / "data_collector" / "tushare").mkdir(parents=True)
        (repo / "scripts" / "data_collector" / "tushare" / "collector.py").write_text("")
        monkeypatch.setenv("MOSAIC_QLIB_REPO", str(repo))

        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["cwd"] = kwargs.get("cwd")
            captured["env"] = kwargs.get("env")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        outcome = qlib_ingest._run_collector(
            "download_data",
            ["--source_dir", "/tmp/raw"],
            stream_stdout=False,
        )
        assert outcome.returncode == 0
        assert outcome.verb == "download_data"
        assert captured["cmd"][1].endswith("collector.py")
        assert captured["cmd"][2] == "download_data"
        assert "--source_dir" in captured["cmd"]


# ---------------------------------------------------------------------------
# Public API command construction
# ---------------------------------------------------------------------------


class TestPublicAPI:
    @pytest.fixture
    def fake_repo(self, tmp_path: Path, monkeypatch) -> Path:
        repo = tmp_path / "fake_qlib"
        (repo / "scripts" / "data_collector" / "tushare").mkdir(parents=True)
        (repo / "scripts" / "data_collector" / "tushare" / "collector.py").write_text("")
        monkeypatch.setenv("MOSAIC_QLIB_REPO", str(repo))
        return repo

    def test_ingest_full_command(self, tmp_path, fake_repo, monkeypatch):
        captured = []

        def fake_run(cmd, **kwargs):
            captured.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(subprocess, "run", fake_run)

        qlib_ingest.ingest_full(
            start="2020-01-01",
            end="2020-12-31",
            qlib_dir=tmp_path / "qlib_out",
            raw_dir=tmp_path / "raw",
            normalize_dir=tmp_path / "norm",
            max_workers=4,
            stream_stdout=True,
        )
        assert len(captured) == 1
        cmd = captured[0]
        assert "pipeline" in cmd
        assert "--start" in cmd
        assert "2020-01-01" in cmd
        assert "--end" in cmd
        assert "2020-12-31" in cmd
        assert "--max_workers" in cmd
        assert "4" in cmd

    def test_ingest_incremental_requires_existing_dir(
        self, tmp_path, fake_repo, monkeypatch
    ):
        with pytest.raises(FileNotFoundError, match="not initialised yet"):
            qlib_ingest.ingest_incremental(
                end="2024-12-31",
                qlib_dir=tmp_path / "no_such_qlib_dir",
            )

    def test_ingest_incremental_with_existing_dir(
        self, tmp_path, fake_repo, monkeypatch
    ):
        qlib_dir = tmp_path / "qlib_out"
        (qlib_dir / "calendars").mkdir(parents=True)
        (qlib_dir / "calendars" / "day.txt").write_text("2024-12-30\n")

        captured = []

        def fake_run(cmd, **kwargs):
            captured.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(subprocess, "run", fake_run)

        qlib_ingest.ingest_incremental(end="2024-12-31", qlib_dir=qlib_dir)
        assert len(captured) == 1
        cmd = captured[0]
        assert "update_data_to_bin" in cmd
        assert "--end_date" in cmd
        assert "2024-12-31" in cmd

    def test_sync_calendar_command(self, tmp_path, fake_repo, monkeypatch):
        captured = []
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda cmd, **kw: (captured.append(cmd), subprocess.CompletedProcess(cmd, 0))[1],
        )
        qlib_ingest.sync_calendar(end="2024-12-31", qlib_dir=tmp_path / "qlib_out")
        assert len(captured) == 1
        assert "sync_calendar" in captured[0]
        assert "--end_date" in captured[0]


# ---------------------------------------------------------------------------
# validate_after_ingest
# ---------------------------------------------------------------------------


def _build_minimal_qlib_dir(qlib_dir: Path, *, calendar_days: int = 250) -> None:
    """Layout a minimal qlib data dir with 3 instruments and varying gaps."""
    (qlib_dir / "calendars").mkdir(parents=True)
    (qlib_dir / "instruments").mkdir(parents=True)
    (qlib_dir / "features").mkdir(parents=True)

    # Calendar: N synthetic dates
    cal_lines = [f"2024-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}" for i in range(calendar_days)]
    (qlib_dir / "calendars" / "day.txt").write_text("\n".join(cal_lines) + "\n")

    # 3 instruments
    instruments = ["sh000300", "sh600519", "sz000001"]
    (qlib_dir / "instruments" / "all.txt").write_text(
        "\n".join(f"{t}\t{cal_lines[0]}\t{cal_lines[-1]}" for t in instruments) + "\n"
    )

    def write_close_bin(ticker: str, n_bars: int, start_idx: int = 0):
        ticker_dir = qlib_dir / "features" / ticker
        ticker_dir.mkdir(parents=True, exist_ok=True)
        # qlib bin: float32 start_idx, then float32 values
        with open(ticker_dir / "close.day.bin", "wb") as f:
            f.write(struct.pack("<f", float(start_idx)))
            f.write(b"\x00" * (n_bars * 4))  # zero-fill 'close' values

    # sh000300: full calendar (no gap)
    write_close_bin("sh000300", calendar_days)
    # sh600519: 50% bars (huge gap → should be flagged)
    write_close_bin("sh600519", calendar_days // 2)
    # sz000001: 99.5% bars (within 1% threshold — should NOT be flagged)
    write_close_bin("sz000001", int(calendar_days * 0.995))


class TestValidateAfterIngest:
    def test_full_universe_no_gaps(self, tmp_path: Path):
        qlib_dir = tmp_path / "qlib_data" / "cn_data"
        _build_minimal_qlib_dir(qlib_dir, calendar_days=200)

        # Override sz000001 to also be full
        ticker_dir = qlib_dir / "features" / "sz000001"
        with open(ticker_dir / "close.day.bin", "wb") as f:
            f.write(struct.pack("<f", 0.0))
            f.write(b"\x00" * (200 * 4))
        # Override sh600519 to be full
        ticker_dir = qlib_dir / "features" / "sh600519"
        with open(ticker_dir / "close.day.bin", "wb") as f:
            f.write(struct.pack("<f", 0.0))
            f.write(b"\x00" * (200 * 4))

        skip_manifest = tmp_path / "skipped.txt"
        report = qlib_ingest.validate_after_ingest(
            qlib_dir=qlib_dir, skip_manifest=skip_manifest, gap_threshold=0.01
        )
        assert report["instruments"] == 3
        assert report["skipped"] == 0
        assert report["calendar_days"] == 200

    def test_gap_threshold_flags_only_bad_tickers(self, tmp_path: Path):
        qlib_dir = tmp_path / "qlib_data" / "cn_data"
        _build_minimal_qlib_dir(qlib_dir, calendar_days=200)

        skip_manifest = tmp_path / "skipped.txt"
        report = qlib_ingest.validate_after_ingest(
            qlib_dir=qlib_dir, skip_manifest=skip_manifest, gap_threshold=0.01
        )
        # sh600519 at 50% should be flagged; sz000001 at 99.5% should not
        assert report["skipped"] == 1
        text = skip_manifest.read_text(encoding="utf-8")
        assert "sh600519" in text
        assert "sz000001" not in text

    def test_missing_close_bin_treated_as_skipped(self, tmp_path: Path):
        qlib_dir = tmp_path / "qlib_data" / "cn_data"
        _build_minimal_qlib_dir(qlib_dir, calendar_days=100)
        # Remove sh000300's close bin entirely
        (qlib_dir / "features" / "sh000300" / "close.day.bin").unlink()

        report = qlib_ingest.validate_after_ingest(
            qlib_dir=qlib_dir,
            skip_manifest=tmp_path / "skipped.txt",
            gap_threshold=0.01,
        )
        assert report["skipped"] >= 1

    def test_layout_incomplete_raises(self, tmp_path: Path):
        bad_dir = tmp_path / "incomplete"
        bad_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="layout incomplete"):
            qlib_ingest.validate_after_ingest(qlib_dir=bad_dir)
