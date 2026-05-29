"""Tests for PRISM 7-cohort training orchestration (Phase 5)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

# Import prism modules directly to avoid pulling in tools.py deps.
import mosaic.bridge.protocol  # noqa: F401

from mosaic.prism.cohorts import (
    get_cohort,
    get_cohort_prompt_dir,
    list_cohorts,
)
from mosaic.prism.trainer import compare_cohorts, ensure_cohort_branch, train_cohort
from mosaic.scorecard.store import ScorecardStore

# Import the prism handler. Prefer the normal package import; fall back to an
# isolated module exec only when the package __init__ can't be imported (no
# langchain). Re-exec'ing after a successful import double-registers @method.
try:
    from mosaic.bridge.handlers import prism as _prism
except Exception:
    _HANDLER_PATH = (
        Path(__file__).resolve().parent.parent
        / "mosaic" / "bridge" / "handlers" / "prism.py"
    )
    _spec = importlib.util.spec_from_file_location(
        "mosaic.bridge.handlers.prism", str(_HANDLER_PATH)
    )
    _prism = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = _prism
    _spec.loader.exec_module(_prism)

_MOD = "mosaic.bridge.handlers.prism"


def _make_git_repo(path: Path) -> None:
    """Initialize a bare-minimum git repo with an initial commit on main."""
    subprocess.run(["git", "init", "-b", "main", str(path)],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "test"],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@test.local"],
                   capture_output=True, check=True)
    readme = path / "README.md"
    readme.write_text("# test\n")
    subprocess.run(["git", "-C", str(path), "add", "."],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "init"],
                   capture_output=True, check=True)


# ---------------------------------------------------------------------------
# Test cohort config
# ---------------------------------------------------------------------------


class TestCohortConfig(unittest.TestCase):
    """Test cohort configuration listing and lookup."""

    def test_list_cohorts_returns_seven(self):
        cohorts = list_cohorts()
        self.assertEqual(len(cohorts), 7)

    def test_list_cohorts_has_correct_keys(self):
        cohorts = list_cohorts()
        for c in cohorts:
            self.assertIn("name", c)
            self.assertIn("start", c)
            self.assertIn("end", c)
            self.assertIn("description", c)

    def test_list_cohorts_correct_dates(self):
        cohorts = list_cohorts()
        by_name = {c["name"]: c for c in cohorts}
        self.assertEqual(by_name["bull_2007"]["start"], "2006-01-04")
        self.assertEqual(by_name["bull_2007"]["end"], "2007-10-16")
        self.assertEqual(by_name["crisis_2008"]["start"], "2007-10-17")
        self.assertEqual(by_name["crisis_2008"]["end"], "2008-10-28")
        self.assertEqual(by_name["rate_tightening"]["start"], "2022-04-01")
        self.assertEqual(by_name["rate_tightening"]["end"], "2023-12-31")

    def test_get_cohort_known(self):
        c = get_cohort("euphoria_2021")
        self.assertEqual(c["name"], "euphoria_2021")
        self.assertEqual(c["start"], "2020-07-01")
        self.assertEqual(c["end"], "2021-02-18")

    def test_get_cohort_unknown_raises(self):
        with self.assertRaises(ValueError):
            get_cohort("nonexistent")

    def test_get_cohort_prompt_dir(self):
        self.assertEqual(get_cohort_prompt_dir("bull_2007"), "cohort_bull_2007")
        self.assertEqual(get_cohort_prompt_dir("crisis_covid"), "cohort_crisis_covid")

    def test_get_cohort_prompt_dir_unknown_raises(self):
        with self.assertRaises(ValueError):
            get_cohort_prompt_dir("nonexistent")


# ---------------------------------------------------------------------------
# Test trainer
# ---------------------------------------------------------------------------


class TestTrainer(unittest.TestCase):
    """Test trainer functions with mocked GitOps."""

    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.db_path = self.tmp / "scorecard.db"
        self.store = ScorecardStore(db_path=self.db_path)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ensure_cohort_branch_creates_branch(self):
        git = MagicMock()
        git.branch_exists.return_value = False
        ensure_cohort_branch(git, "bull_2007")
        git.branch_exists.assert_called_once_with("cohort/bull_2007/main")
        git.create_branch.assert_called_once_with("cohort/bull_2007/main", "main")

    def test_ensure_cohort_branch_skips_existing(self):
        git = MagicMock()
        git.branch_exists.return_value = True
        ensure_cohort_branch(git, "bull_2007")
        git.branch_exists.assert_called_once_with("cohort/bull_2007/main")
        git.create_branch.assert_not_called()

    def test_train_cohort_dry_run(self):
        git = MagicMock()
        result = train_cohort(self.store, git, "bull_2007", dry_run=True)
        self.assertFalse(result["started"])
        self.assertEqual(result["cohort"], "bull_2007")
        self.assertIn("dry-run", result["message"])
        # Should NOT create branch or run entry in dry run.
        git.branch_exists.assert_not_called()
        git.create_branch.assert_not_called()

    def test_train_cohort_creates_run(self):
        git = MagicMock()
        git.branch_exists.return_value = False
        result = train_cohort(self.store, git, "crisis_2008")
        self.assertTrue(result["started"])
        self.assertEqual(result["cohort"], "crisis_2008")
        self.assertIn("run_id", result)
        # Verify run was stored.
        runs = self.store.get_cohort_runs("crisis_2008")
        self.assertEqual(len(runs), 1)

    def test_train_cohort_unknown_raises(self):
        git = MagicMock()
        with self.assertRaises(ValueError):
            train_cohort(self.store, git, "nonexistent")

    def test_compare_cohorts_structure(self):
        result = compare_cohorts(self.store)
        self.assertEqual(len(result), 7)
        for entry in result:
            self.assertIn("cohort", entry)
            self.assertIn("n_runs", entry)
            self.assertIn("n_mutations", entry)
            self.assertIn("n_kept", entry)
            self.assertIn("n_reverted", entry)
            self.assertIn("latest_date", entry)


# ---------------------------------------------------------------------------
# Test store cohort_runs methods
# ---------------------------------------------------------------------------


class TestStoreCohortRuns(unittest.TestCase):
    """Test ScorecardStore cohort_runs table operations."""

    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.db_path = self.tmp / "scorecard.db"
        self.store = ScorecardStore(db_path=self.db_path)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_create_cohort_run(self):
        run_id = self.store.create_cohort_run("bull_2007", "2024-01-15")
        self.assertIsInstance(run_id, int)
        self.assertGreater(run_id, 0)

    def test_create_cohort_run_idempotent(self):
        id1 = self.store.create_cohort_run("bull_2007", "2024-01-15")
        id2 = self.store.create_cohort_run("bull_2007", "2024-01-15")
        self.assertEqual(id1, id2)

    def test_complete_cohort_run(self):
        run_id = self.store.create_cohort_run("bull_2007", "2024-01-15")
        self.store.complete_cohort_run(
            run_id, llm_calls=42, llm_cost_usd=1.5,
            cio_action="BUY", cio_target_weight=0.05,
        )
        runs = self.store.get_cohort_runs("bull_2007")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["llm_calls"], 42)
        self.assertAlmostEqual(runs[0]["llm_cost_usd"], 1.5)
        self.assertEqual(runs[0]["cio_action"], "BUY")
        self.assertIsNotNone(runs[0]["cycle_completed_at"])

    def test_get_cohort_runs_since_date(self):
        self.store.create_cohort_run("bull_2007", "2024-01-10")
        self.store.create_cohort_run("bull_2007", "2024-01-20")
        runs = self.store.get_cohort_runs("bull_2007", since_date="2024-01-15")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["date"], "2024-01-20")

    def test_get_cohort_runs_limit(self):
        for i in range(5):
            self.store.create_cohort_run("bull_2007", f"2024-01-{10 + i:02d}")
        runs = self.store.get_cohort_runs("bull_2007", limit=3)
        self.assertEqual(len(runs), 3)

    def test_get_cohort_status_summary(self):
        self.store.create_cohort_run("crisis_2008", "2024-01-10")
        self.store.create_cohort_run("crisis_2008", "2024-01-11")
        summary = self.store.get_cohort_status_summary("crisis_2008")
        self.assertEqual(summary["cohort"], "crisis_2008")
        self.assertEqual(summary["n_runs"], 2)
        self.assertEqual(summary["last_date"], "2024-01-11")
        self.assertEqual(summary["n_mutations"], 0)
        self.assertIsNone(summary["sharpe_latest"])

    def test_get_cohort_status_summary_empty(self):
        summary = self.store.get_cohort_status_summary("nonexistent")
        self.assertEqual(summary["n_runs"], 0)
        self.assertIsNone(summary["last_date"])


# ---------------------------------------------------------------------------
# Test prism handler (RPC)
# ---------------------------------------------------------------------------


class TestPrismHandler(unittest.TestCase):
    """Test prism.* RPC handlers."""

    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.db_path = self.tmp / "scorecard.db"
        self.repo_path = self.tmp / "repo"
        self.repo_path.mkdir()
        _make_git_repo(self.repo_path)

        self.store = ScorecardStore(db_path=self.db_path)
        self._store_patch = patch.object(_prism, "_store", return_value=self.store)
        self._repo_patch = patch.object(_prism, "_repo_root", return_value=self.repo_path)
        self._store_patch.start()
        self._repo_patch.start()

    def tearDown(self):
        self._store_patch.stop()
        self._repo_patch.stop()
        self._tmpdir.cleanup()

    def test_list_cohorts(self):
        result = _prism.prism_list_cohorts({})
        self.assertIn("cohorts", result)
        self.assertEqual(len(result["cohorts"]), 7)
        first = result["cohorts"][0]
        self.assertIn("name", first)
        self.assertIn("has_branch", first)
        self.assertIn("n_runs", first)

    def test_train_cohort_dry_run(self):
        result = _prism.prism_train_cohort({
            "cohort_name": "bull_2007",
            "dry_run": True,
        })
        self.assertFalse(result["started"])
        self.assertIn("dry-run", result["message"])

    def test_train_cohort_live(self):
        result = _prism.prism_train_cohort({
            "cohort_name": "crisis_2008",
        })
        self.assertTrue(result["started"])
        self.assertIn("run_id", result)

    def test_cohort_status(self):
        result = _prism.prism_cohort_status({"cohort_name": "bull_2007"})
        self.assertEqual(result["cohort"], "bull_2007")
        self.assertIn("n_runs", result)
        self.assertIn("n_mutations", result)

    def test_cohort_status_unknown_raises(self):
        from mosaic.bridge.protocol import RpcError
        with self.assertRaises((RpcError, ValueError)):
            _prism.prism_cohort_status({"cohort_name": "nonexistent"})

    def test_compare_cohorts(self):
        result = _prism.prism_compare_cohorts({})
        self.assertIn("comparisons", result)
        self.assertEqual(len(result["comparisons"]), 7)

    def test_complete_cohort_run_closes_ledger(self):
        # Open a run, then close it via the RPC and verify the ledger row.
        run_id = self.store.create_cohort_run("crisis_2008", "2024-01-15")
        result = _prism.prism_complete_cohort_run({
            "run_id": run_id,
            "llm_calls": 25,
        })
        self.assertTrue(result["ok"])
        runs = self.store.get_cohort_runs("crisis_2008")
        row = next(r for r in runs if r["id"] == run_id)
        self.assertIsNotNone(row["cycle_completed_at"])
        self.assertEqual(row["llm_calls"], 25)

    def test_complete_cohort_run_rejects_bad_run_id(self):
        from mosaic.bridge.protocol import RpcError
        with self.assertRaises(RpcError):
            _prism.prism_complete_cohort_run({"run_id": "nope"})


if __name__ == "__main__":
    unittest.main()
