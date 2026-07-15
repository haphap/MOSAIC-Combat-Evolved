from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[1] / "scripts" / "run_with_kde_vram_guard.py"
_SPEC = importlib.util.spec_from_file_location("run_with_kde_vram_guard", _SCRIPT)
assert _SPEC and _SPEC.loader
guard = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = guard
_SPEC.loader.exec_module(guard)


def _fake_nvidia_smi(path: Path, samples: list[int], *, hang_after_first: bool = False) -> Path:
    values = ", ".join(str(value) for value in samples)
    path.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        "import time\n"
        f"samples = [{values}]\n"
        f"hang_after_first = {hang_after_first!r}\n"
        "counter = Path(__file__).with_suffix('.count')\n"
        "index = int(counter.read_text()) if counter.exists() else 0\n"
        "counter.write_text(str(index + 1))\n"
        "if hang_after_first and index > 0:\n"
        "    time.sleep(10)\n"
        "free = samples[min(index, len(samples) - 1)]\n"
        "print(f'100, {free}, 50, 60')\n"
    )
    path.chmod(0o755)
    return path


def _run_guard(
    tmp_path: Path,
    samples: list[int],
    child_code: str,
    *,
    hang_after_first: bool = False,
) -> subprocess.CompletedProcess[str]:
    output = tmp_path / "samples.csv"
    nvidia_smi = _fake_nvidia_smi(
        tmp_path / "nvidia-smi", samples, hang_after_first=hang_after_first
    )
    return subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--output",
            str(output),
            "--interval-seconds",
            "0.01",
            "--termination-grace-seconds",
            "0.1",
            "--gpu-query-timeout-seconds",
            "0.05",
            "--nvidia-smi",
            str(nvidia_smi),
            "--skip-kde-log-check",
            "--",
            sys.executable,
            "-c",
            child_code,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )


def test_parse_gpu_sample_requires_exactly_one_gpu() -> None:
    sample = guard.parse_gpu_sample("100, 2048, 50, 60\n", timestamp="now")
    assert sample.memory_free_mib == 2048
    assert sample.timestamp == "now"

    with pytest.raises(ValueError, match="expected one GPU"):
        guard.parse_gpu_sample("100, 2048, 50, 60\n100, 2048, 50, 60\n")


def test_guard_records_minimum_headroom_for_successful_command(tmp_path: Path) -> None:
    result = _run_guard(tmp_path, [2048, 1800, 1536], "import time; time.sleep(0.12)")

    assert result.returncode == 0, result.stderr
    summary = json.loads((tmp_path / "samples.csv.summary.json").read_text())
    assert summary["minimum_free_mib_observed"] == 1536
    assert summary["violation"] is None
    assert summary["child_returncode"] == 0


def test_guard_stops_command_when_headroom_crosses_floor(tmp_path: Path) -> None:
    result = _run_guard(tmp_path, [2048, 128], "import time; time.sleep(10)")

    assert result.returncode == guard.GUARD_EXIT_CODE
    summary = json.loads((tmp_path / "samples.csv.summary.json").read_text())
    assert summary["minimum_free_mib_observed"] == 128
    assert summary["violation"] == "free_vram_below_threshold"
    assert summary["child_returncode"] != 0


def test_guard_stops_command_when_gpu_query_hangs(tmp_path: Path) -> None:
    result = _run_guard(
        tmp_path,
        [2048],
        "import time; time.sleep(10)",
        hang_after_first=True,
    )

    assert result.returncode == guard.GUARD_EXIT_CODE
    summary = json.loads((tmp_path / "samples.csv.summary.json").read_text())
    assert summary["violation"] == "gpu_sampling_failed"
    assert summary["error"] == "nvidia-smi timed out after 0.05 seconds"
    assert summary["child_returncode"] != 0


def test_guard_defaults_to_compute_card_floor() -> None:
    assert guard.MINIMUM_FREE_MIB == 256
