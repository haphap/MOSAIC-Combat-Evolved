"""Tests for read-only PRISM cohort configuration and audit RPCs."""

from __future__ import annotations

import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from mosaic.bridge.handlers import prism as handlers
from mosaic.bridge.registry import all_methods
from mosaic.prism.audit import compare_cohorts
from mosaic.prism.cohorts import get_cohort, get_cohort_prompt_dir, list_cohorts
from mosaic.scorecard.store import ScorecardStore


def _make_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "test"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.invalid"],
        check=True,
        capture_output=True,
    )
    (path / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "init"], check=True, capture_output=True)


def test_cohort_configuration_is_stable() -> None:
    cohorts = list_cohorts()
    assert len(cohorts) == 7
    assert get_cohort("euphoria_2021")["start"] == "2020-07-01"
    assert get_cohort_prompt_dir("crisis_covid") == "cohort_crisis_covid"
    with pytest.raises(ValueError):
        get_cohort("unknown")


def test_prism_writer_rpcs_are_absent() -> None:
    assert "prism.train_cohort" not in all_methods()
    assert "prism.complete_cohort_run" not in all_methods()
    assert not hasattr(handlers, "prism_train_cohort")
    assert not hasattr(handlers, "prism_complete_cohort_run")


def test_compare_cohorts_reads_empty_history(tmp_path: Path) -> None:
    store = ScorecardStore(db_path=tmp_path / "scorecard.db")
    rows = compare_cohorts(store)
    assert len(rows) == 7
    assert all(row["n_runs"] == 0 and row["n_mutations"] == 0 for row in rows)


def test_read_only_prism_handlers(tmp_path: Path) -> None:
    store = ScorecardStore(db_path=tmp_path / "scorecard.db")
    with TemporaryDirectory() as directory:
        repo = Path(directory) / "repo"
        repo.mkdir()
        _make_git_repo(repo)
        with (
            patch.object(handlers, "_store", return_value=store),
            patch.object(handlers, "_repo_root", return_value=repo),
        ):
            assert len(handlers.prism_list_cohorts({})["cohorts"]) == 7
            assert handlers.prism_cohort_status({"cohort_name": "bull_2007"})[
                "n_runs"
            ] == 0
            assert len(handlers.prism_compare_cohorts({})["comparisons"]) == 7
