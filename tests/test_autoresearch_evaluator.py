"""Tests for mosaic.autoresearch.evaluator (Plan ss11.5 4C)."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mosaic.autoresearch.evaluator import (
    compute_delta,
    ensure_baseline_run,
    has_output_section,
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

    def test_repo_aware_run_matches_commit_ref_and_metadata(self):
        run_id = self.store.create_backtest_run(
            cohort="euphoria_2021",
            start_date="2020-07-01",
            end_date="2021-02-18",
            prompt_commit_hash="abc123",
            prompt_repo_id="private",
            prompt_sha256="f" * 64,
            code_commit_hash="c" * 40,
        )
        self.store.complete_backtest_run(run_id)

        result = ensure_baseline_run(
            self.store,
            "euphoria_2021",
            "2020-07-01",
            "2021-02-18",
            "abc123",
            prompt_repo_id="private",
            prompt_sha256="f" * 64,
            code_commit_hash="c" * 40,
        )
        self.assertEqual(result["run_id"], run_id)
        self.assertFalse(result["needs_fill"])

    def test_repo_aware_run_rejects_metadata_mismatch(self):
        run_id = self.store.create_backtest_run(
            cohort="euphoria_2021",
            start_date="2020-07-01",
            end_date="2021-02-18",
            prompt_commit_hash="abc123",
            prompt_repo_id="private",
            prompt_sha256="f" * 64,
            code_commit_hash="c" * 40,
        )
        self.store.complete_backtest_run(run_id)

        result = ensure_baseline_run(
            self.store,
            "euphoria_2021",
            "2020-07-01",
            "2021-02-18",
            "abc123",
            prompt_repo_id="private",
            prompt_sha256="0" * 64,
            code_commit_hash="c" * 40,
        )
        self.assertIsNone(result["run_id"])
        self.assertTrue(result["needs_fill"])


class TestPromptToolCompatibility(unittest.TestCase):
    """Tests for the registry-scan compatibility gate."""

    def test_has_output_section_is_anchored_on_schema(self):
        # real headers match
        self.assertTrue(has_output_section("## Output schema\n- x"))
        self.assertTrue(has_output_section("## 输出 schema\n- x"))
        self.assertTrue(has_output_section("### output  schema"))
        # unrelated headers containing output/输出 do NOT count as the gate
        self.assertFalse(has_output_section("## Tool output format"))
        self.assertFalse(has_output_section("## 输出语言设置"))

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
                return "Use get_macro_data.\n## Output schema\n- x"

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

    def test_validate_flags_dropped_output_section(self):
        class FakeModGit:
            # mutation stripped the output-schema section
            def show_file(self, _ref: str, _path: str) -> str:
                return "Use get_macro_data. (no output section)"

        class FakeBaselineGit:
            # project baseline still has it
            def show_file(self, _ref: str, _path: str) -> str:
                return "Use get_macro_data.\n## Output schema\n- field"

        result = validate_prompt_tool_compatibility(
            {
                "cohort": "euphoria_2021",
                "agent": "volatility",
                "modification_commit_hash": "b" * 40,
                "base_commit_hash": "a" * 40,
            },
            FakeModGit(),
            available_tools={"get_macro_data"},
            baseline_git=FakeBaselineGit(),
        )
        self.assertFalse(result["compatible"])
        self.assertEqual(len(result["dropped_output_sections"]), 2)  # zh + en

    def test_validate_allows_drop_when_baseline_lacks_section(self):
        class FakeModGit:
            def show_file(self, _ref: str, _path: str) -> str:
                return "Use get_macro_data."

        class FakeBaselineGit:
            def show_file(self, _ref: str, _path: str) -> str:
                return "Use get_macro_data."  # baseline never had a section

        result = validate_prompt_tool_compatibility(
            {
                "cohort": "euphoria_2021",
                "agent": "volatility",
                "modification_commit_hash": "b" * 40,
                "base_commit_hash": "a" * 40,
            },
            FakeModGit(),
            available_tools={"get_macro_data"},
            baseline_git=FakeBaselineGit(),
        )
        self.assertTrue(result["compatible"])
        self.assertEqual(result["dropped_output_sections"], [])


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
