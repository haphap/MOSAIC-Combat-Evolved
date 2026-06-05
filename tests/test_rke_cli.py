from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke.cli import main


def _copy_registry(dst_root: Path) -> None:
    shutil.copytree(Path("registry"), dst_root / "registry")


def test_rke_cli_validate_required_success(capsys):
    code = main(("validate-required", "--root", "."))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["valid"] is True
    assert output["missing_required"] == []


def test_rke_cli_validate_required_failure(tmp_path: Path, capsys):
    code = main(("validate-required", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output["valid"] is False
    assert "registry/audits/rke_completion_audit.json" in output["missing_required"]


def test_rke_cli_manifest_writes_file(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(("manifest", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["valid"] is True
    assert Path(output["path"]).exists()


def test_rke_cli_refresh_preserves_reviews(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    gold_review = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    original = gold_review.read_text(encoding="utf-8")

    code = main(("refresh", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["manifest_valid"] is True
    assert gold_review.read_text(encoding="utf-8") == original


def test_pyproject_exposes_mosaic_rke_console_script():
    text = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'mosaic-rke = "mosaic.rke.cli:main"' in text
