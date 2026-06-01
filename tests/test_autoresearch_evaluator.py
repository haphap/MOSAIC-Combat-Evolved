"""Tests for mosaic.autoresearch.evaluator (Plan ss11.5 4C)."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mosaic.autoresearch.evaluator import (
    compute_delta,
    ensure_baseline_run,
    scan_prompt_tool_tokens,
    validate_prompt_tool_compatibility,
)
from mosaic.scorecard.store import ScorecardStore


class TestEnsureBaselineRun(unittest.TestCase):
    """Tests for ensure_baseline_run: cache hit vs. needs_fill."""

    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "scorecard.db"
        self.store = ScorecardStore(db_path=self.db_path)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_needs_fill_when_no_run_exists(self):
        result = ensure_baseline_run(
            self.store, "euphoria_2021", "2020-07-01", "2021-02-18", "abc123"
        )
        self.assertIsNone(result["run_id"])
        self.assertTrue(result["needs_fill"])

    def test_needs_fill_when_run_not_completed(self):
        # Create an incomplete run.
        self.store.create_backtest_run(
            cohort="euphoria_2021",
            start_date="2020-07-01",
            end_date="2021-02-18",
            prompt_commit_hash="abc123",
        )
        result = ensure_baseline_run(
            self.store, "euphoria_2021", "2020-07-01", "2021-02-18", "abc123"
        )
        self.assertIsNone(result["run_id"])
        self.assertTrue(result["needs_fill"])

    def test_cache_hit_when_run_completed(self):
        run_id = self.store.create_backtest_run(
            cohort="euphoria_2021",
            start_date="2020-07-01",
            end_date="2021-02-18",
            prompt_commit_hash="abc123",
        )
        self.store.complete_backtest_run(run_id)
        result = ensure_baseline_run(
            self.store, "euphoria_2021", "2020-07-01", "2021-02-18", "abc123"
        )
        self.assertEqual(result["run_id"], run_id)
        self.assertFalse(result["needs_fill"])

    def test_different_commit_is_cache_miss(self):
        run_id = self.store.create_backtest_run(
            cohort="euphoria_2021",
            start_date="2020-07-01",
            end_date="2021-02-18",
            prompt_commit_hash="abc123",
        )
        self.store.complete_backtest_run(run_id)
        # Different commit hash.
        result = ensure_baseline_run(
            self.store, "euphoria_2021", "2020-07-01", "2021-02-18", "def456"
        )
        self.assertIsNone(result["run_id"])
        self.assertTrue(result["needs_fill"])


class TestPromptToolCompatibility(unittest.TestCase):
    """Tests for the registry-scan compatibility gate."""

    def test_scan_prompt_tool_tokens(self):
        tokens = scan_prompt_tool_tokens(
            "Use get_macro_data, get_industry_moneyflow and get_macro_data again. "
            "Ignore get-typo and forget_tool."
        )
        self.assertEqual(tokens, {"get_macro_data", "get_industry_moneyflow"})

    def test_validate_unknown_tools(self):
        class FakeGit:
            def show_file(self, _ref: str, path: str) -> str:
                if path.endswith(".zh.md"):
                    return "Use get_macro_data and get_removed_tool."
                return "Use get_macro_data."

        result = validate_prompt_tool_compatibility(
            {
                "cohort": "euphoria_2021",
                "agent": "volatility",
                "modification_commit_hash": "b" * 40,
            },
            FakeGit(),
            available_tools={"get_macro_data"},
        )
        self.assertFalse(result["compatible"])
        self.assertEqual(result["unknown_tools"], ["get_removed_tool"])
        self.assertEqual(result["missing_files"], [])

    def test_validate_known_tools(self):
        class FakeGit:
            def show_file(self, _ref: str, _path: str) -> str:
                return "Use get_macro_data."

        result = validate_prompt_tool_compatibility(
            {
                "cohort": "euphoria_2021",
                "agent": "volatility",
                "modification_commit_hash": "b" * 40,
            },
            FakeGit(),
            available_tools={"get_macro_data"},
        )
        self.assertTrue(result["compatible"])


class TestComputeDelta(unittest.TestCase):
    """Tests for compute_delta: correct calculation and error cases."""

    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "scorecard.db"
        self.store = ScorecardStore(db_path=self.db_path)
        self.config = {
            "cohorts": {
                "euphoria_2021": {"start": "2020-07-01", "end": "2021-02-18"},
            },
            "autoresearch": {
                "keep_threshold_delta_sharpe": 0.1,
            },
        }

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_raises_when_version_not_found(self):
        with self.assertRaises(ValueError) as ctx:
            compute_delta(self.store, 9999, self.config)
        self.assertIn("not found", str(ctx.exception))

    def test_raises_when_no_modification_commit(self):
        version_id = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name="cohort/euphoria_2021/auto/volatility/2021-01-01",
            base_commit_hash="a" * 40,
        )
        with self.assertRaises(ValueError) as ctx:
            compute_delta(self.store, version_id, self.config)
        self.assertIn("modification_commit_hash", str(ctx.exception))

    def test_raises_when_base_run_missing(self):
        base_commit = "a" * 40
        mod_commit = "b" * 40
        version_id = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name="cohort/euphoria_2021/auto/volatility/2021-01-01",
            base_commit_hash=base_commit,
        )
        self.store.set_version_mutation(version_id, mod_commit, "test mutation")

        with self.assertRaises(ValueError) as ctx:
            compute_delta(self.store, version_id, self.config)
        self.assertIn("no completed base", str(ctx.exception))

    def test_raises_when_mod_run_missing(self):
        base_commit = "a" * 40
        mod_commit = "b" * 40
        version_id = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name="cohort/euphoria_2021/auto/volatility/2021-01-01",
            base_commit_hash=base_commit,
        )
        self.store.set_version_mutation(version_id, mod_commit, "test mutation")

        # Create and complete base run only.
        run_id = self.store.create_backtest_run(
            cohort="euphoria_2021",
            start_date="2020-07-01",
            end_date="2021-02-18",
            prompt_commit_hash=base_commit,
        )
        self.store.complete_backtest_run(run_id)

        with self.assertRaises(ValueError) as ctx:
            compute_delta(self.store, version_id, self.config)
        self.assertIn("no completed mod", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
