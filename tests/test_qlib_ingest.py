"""Tests for mosaic.dataflows.qlib_ingest (Plan §11.3 sub-step 3.5B)."""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

import pandas as pd
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
        # Patch away the vendored copy so the not-found path is reachable.
        monkeypatch.setattr(qlib_ingest, "_VENDORED_DC_DIR", tmp_path / "no_vendored")

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
        # Patch away the vendored copy so the not-found path is reachable.
        monkeypatch.setattr(qlib_ingest, "_VENDORED_DC_DIR", tmp_path / "no_vendored")
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

        qlib_ingest.ingest_incremental(
            end="2024-12-31",
            qlib_dir=qlib_dir,
            raw_dir=tmp_path / "raw",
            normalize_dir=tmp_path / "norm",
        )
        assert len(captured) == 1
        cmd = captured[0]
        assert "update_data_to_bin_batch" in cmd
        assert "--end_date" in cmd
        assert "2024-12-31" in cmd
        # Anti-pollution: collector working dirs are pinned out of the repo so
        # update_data_to_bin's __inc_tmp__ never lands under the vendored tree.
        assert "--source_dir" in cmd and "--normalize_dir" in cmd
        repo_collectors = str(Path(qlib_ingest.__file__).resolve().parent / "collectors")
        assert not any(repo_collectors in str(a) for a in cmd)
        assert str((tmp_path / "raw")) in cmd

    def test_etf_incremental_uses_batch_collector(
        self, tmp_path, fake_repo, monkeypatch
    ):
        qlib_dir = tmp_path / "qlib_etf"
        (qlib_dir / "calendars").mkdir(parents=True)
        (qlib_dir / "calendars" / "day.txt").write_text("2024-12-30\n")

        captured = []

        def fake_run(cmd, **kwargs):
            captured.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(subprocess, "run", fake_run)

        qlib_ingest.ingest_incremental(
            end="2024-12-31",
            kind="etf",
            qlib_dir=qlib_dir,
            raw_dir=tmp_path / "raw",
            normalize_dir=tmp_path / "norm",
        )
        assert len(captured) == 1
        assert "update_data_to_bin_batch" in captured[0]

    def test_etf_full_uses_batch_pipeline(
        self, tmp_path, fake_repo, monkeypatch
    ):
        captured = []

        def fake_run(cmd, **kwargs):
            captured.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(subprocess, "run", fake_run)

        qlib_ingest.ingest_full(
            start="2000-01-01",
            end="2026-06-03",
            kind="etf",
            qlib_dir=tmp_path / "qlib_etf_full",
            raw_dir=tmp_path / "raw",
            normalize_dir=tmp_path / "norm",
        )

        assert len(captured) == 1
        assert "pipeline_batch" in captured[0]
        assert "--detect_new_etfs=False" in captured[0]
        assert "--parallel_dates=True" in captured[0]

    def test_incremental_cli_exposes_kind_and_default_etf_dir(self, monkeypatch):
        captured = {}

        def fake_ingest_incremental(**kwargs):
            captured.update(kwargs)
            return qlib_ingest.IngestOutcome(
                verb="update_data_to_bin_batch",
                returncode=0,
                stdout_tail="",
                stderr_tail="",
                qlib_dir=qlib_ingest.DEFAULT_QLIB_ETF_DATA_DIR,
            )

        monkeypatch.setattr(qlib_ingest, "ingest_incremental", fake_ingest_incremental)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "mosaic.dataflows.qlib_ingest",
                "incremental",
                "--kind",
                "etf",
                "--end",
                "2026-06-10",
            ],
        )

        assert qlib_ingest._cli() == 0
        assert captured["kind"] == "etf"
        assert captured["qlib_dir"] is None
        assert captured["end"] == "2026-06-10"

    def test_stock_symbols_from_jsonl_extracts_explicit_stock_targets(self, tmp_path: Path):
        source = tmp_path / "claims.jsonl"
        source.write_text(
            "\n".join(
                [
                    '{"ts_code":"000001.SZ"}',
                    '{"target":{"target_type":"stock","target_id":"600000.SH"}}',
                    '{"target":{"target_type":"stock","target_id":"830000.BJ"}}',
                    '{"ts_code":"501001.SH"}',
                    '{"ts_code":"160621.SZ"}',
                    '{"target":{"target_type":"industry","target_id":"银行"}}',
                    '{"proxy_symbol":"920181.BJ"}',
                    '{"target":{"target_type":"stock","target_id":"921181.BJ"}}',
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        assert qlib_ingest.stock_symbols_from_jsonl(source) == [
            "000001.SZ",
            "600000.SH",
            "920181.BJ",
            "921181.BJ",
        ]

    def test_backfill_stock_symbols_fetches_batches_and_rebuilds_only_targets(
        self, tmp_path: Path, monkeypatch
    ):
        pytest.importorskip("qlib", reason="qlib not installed (.[backtest] extra)")
        pytest.importorskip("loguru", reason="ingest extra not installed")
        from mosaic.dataflows.collectors.data_collector.tushare import collector

        qlib_dir = tmp_path / "qlib"
        (qlib_dir / "calendars").mkdir(parents=True)
        (qlib_dir / "calendars" / "day.txt").write_text(
            "2024-01-02\n2024-01-03\n",
            encoding="utf-8",
        )
        raw_dir = tmp_path / "raw"
        norm_dir = tmp_path / "norm"
        requests: list[str] = []

        class FakePro:
            def daily(self, *, ts_code, start_date, end_date):
                requests.append(ts_code)
                rows = []
                for code in ts_code.split(","):
                    rows.append(
                        {
                            "ts_code": code,
                            "trade_date": "20240102",
                            "open": 10.0,
                            "high": 10.5,
                            "low": 9.8,
                            "close": 10.2,
                            "vol": 1000.0,
                            "amount": 10000.0,
                        }
                    )
                return pd.DataFrame(rows)

            def adj_factor(self, *, ts_code, start_date, end_date):
                return pd.DataFrame(
                    [
                        {
                            "ts_code": code,
                            "trade_date": "20240102",
                            "adj_factor": 1.0,
                        }
                        for code in ts_code.split(",")
                    ]
                )

        class FakeTs:
            @staticmethod
            def pro_api(token, timeout):
                assert token == "token"
                assert timeout == 7
                return FakePro()

        repair_seen: dict[str, object] = {}

        def fake_repair(**kwargs):
            repair_seen.update(kwargs)
            return {"rebuilt_count": len(kwargs["csv_files"])}

        monkeypatch.setattr(collector, "ts", FakeTs)
        monkeypatch.setattr(collector, "_get_token", lambda: "token")
        monkeypatch.setattr(collector, "repair_feature_bins_from_normalize", fake_repair)

        outcome = qlib_ingest.backfill_stock_symbols(
            symbols=["000001.SZ,600000.SH"],
            start="2024-01-01",
            end="2024-01-03",
            qlib_dir=qlib_dir,
            raw_dir=raw_dir,
            normalize_dir=norm_dir,
            timeout=7,
            request_symbol_batch_size=2,
        )

        assert outcome.returncode == 0
        assert requests == ["000001.SZ,600000.SH"]
        assert "requested_symbols=2" in outcome.stdout_tail
        csv_names = sorted(path.name for path in repair_seen["csv_files"])
        assert csv_names == ["sh600000.csv", "sz000001.csv"]
        assert (norm_dir / "sz000001.csv").exists()
        assert (raw_dir / "stock_backfill_0001_20240101_20240103.csv").exists()

    def test_backfill_symbols_cli_accepts_jsonl_and_symbols(self, tmp_path: Path, monkeypatch):
        source = tmp_path / "targets.jsonl"
        source.write_text('{"ts_code":"000001.SZ"}\n', encoding="utf-8")
        captured = {}

        def fake_backfill_stock_symbols(**kwargs):
            captured.update(kwargs)
            return qlib_ingest.IngestOutcome(
                verb="backfill_symbols",
                returncode=0,
                stdout_tail="ok",
                stderr_tail="",
                qlib_dir=tmp_path / "qlib",
            )

        monkeypatch.setattr(
            qlib_ingest, "backfill_stock_symbols", fake_backfill_stock_symbols
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "mosaic.dataflows.qlib_ingest",
                "backfill-symbols",
                "--start",
                "2024-01-01",
                "--end",
                "2024-01-31",
                "--symbols",
                "600000.SH",
                "--symbols-jsonl",
                str(source),
                "--request-symbol-batch-size",
                "2",
            ],
        )

        assert qlib_ingest._cli() == 0
        assert captured["symbols"] == ["600000.SH", "000001.SZ"]
        assert captured["start"] == "2024-01-01"
        assert captured["request_symbol_batch_size"] == 2

    def test_incremental_default_dirs_are_out_of_repo(self, tmp_path, fake_repo, monkeypatch):
        """With no raw_dir/normalize_dir, collector working dirs default to
        ~/.cache (out of the repo) — never under mosaic/dataflows/collectors."""
        qlib_dir = tmp_path / "qlib_out"
        (qlib_dir / "calendars").mkdir(parents=True)
        (qlib_dir / "calendars" / "day.txt").write_text("2024-12-30\n")
        captured = []
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda cmd, **kw: (captured.append(cmd), subprocess.CompletedProcess(cmd, 0))[1],
        )
        qlib_ingest.ingest_incremental(end="2024-12-31", qlib_dir=qlib_dir)
        cmd = captured[0]
        src = cmd[cmd.index("--source_dir") + 1]
        norm = cmd[cmd.index("--normalize_dir") + 1]
        repo_collectors = str(Path(qlib_ingest.__file__).resolve().parent / "collectors")
        assert repo_collectors not in src and repo_collectors not in norm
        assert ".cache" in src and ".cache" in norm

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


# ---------------------------------------------------------------------------
# R-P1: qlib bin-header parse (fail-loud on format drift)
# ---------------------------------------------------------------------------


class TestQlibBinHeader:
    def test_valid_header_returns_start_index(self):
        data = struct.pack("<f", 5.0) + b"\x00" * 40
        assert qlib_ingest._qlib_bin_start_index(data, calendar_days=100) == 5

    def test_too_short_raises(self):
        with pytest.raises(qlib_ingest.QlibBinFormatError, match="too short"):
            qlib_ingest._qlib_bin_start_index(b"\x00\x00", calendar_days=100)

    def test_non_integer_header_raises(self):
        # 3.7 is finite but not (near-)integer → format drift signal.
        data = struct.pack("<f", 3.7) + b"\x00" * 8
        with pytest.raises(qlib_ingest.QlibBinFormatError, match="not a finite integer"):
            qlib_ingest._qlib_bin_start_index(data, calendar_days=100)

    def test_out_of_range_header_raises(self):
        data = struct.pack("<f", 999.0) + b"\x00" * 8
        with pytest.raises(qlib_ingest.QlibBinFormatError, match="out of range"):
            qlib_ingest._qlib_bin_start_index(data, calendar_days=100)

    def test_validate_counts_format_errors(self, tmp_path: Path):
        # Build a minimal qlib dir with one ticker whose close.bin header is
        # garbage → validate should count it as a format_error, not crash.
        qlib_dir = tmp_path / "cn_data"
        (qlib_dir / "calendars").mkdir(parents=True)
        (qlib_dir / "calendars" / "day.txt").write_text(
            "\n".join(f"2024-01-{d:02d}" for d in range(1, 11)) + "\n", encoding="utf-8"
        )
        (qlib_dir / "instruments").mkdir()
        (qlib_dir / "instruments" / "all.txt").write_text("sh600000\n", encoding="utf-8")
        feat = qlib_dir / "features" / "sh600000"
        feat.mkdir(parents=True)
        # Header = NaN (not finite) + some values → triggers QlibBinFormatError.
        (feat / "close.day.bin").write_bytes(struct.pack("<f", float("nan")) + b"\x00" * 8)

        report = qlib_ingest.validate_after_ingest(
            qlib_dir=qlib_dir, skip_manifest=tmp_path / "skipped.txt"
        )
        assert report["format_errors"] == 1
        assert report["skipped"] >= 1
