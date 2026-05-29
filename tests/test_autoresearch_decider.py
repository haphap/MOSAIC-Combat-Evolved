"""Tests for mosaic.autoresearch.decider (Plan ss11.5 4D)."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from mosaic.autoresearch.decider import decide
from mosaic.scorecard.store import ScorecardStore


class TestDecideKeep(unittest.TestCase):
    """Test the keep path (delta >= threshold)."""

    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "scorecard.db"
        self.store = ScorecardStore(db_path=self.db_path)
        self.git_ops = MagicMock()
        self.config = {
            "autoresearch": {
                "keep_threshold_delta_sharpe": 0.1,
            }
        }

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_keep_when_delta_above_threshold(self):
        version_id = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name="cohort/euphoria_2021/auto/volatility/2021-01-01",
            base_commit_hash="a" * 40,
        )
        self.store.set_version_eval(version_id, 0.5, 0.7, 0.2)
        version = self.store.get_prompt_version(version_id)

        result = decide(self.store, self.git_ops, version, self.config)

        self.assertEqual(result, "keep")
        self.git_ops.merge_to_main.assert_called_once_with(
            "cohort/euphoria_2021/auto/volatility/2021-01-01"
        )
        # Verify store was updated.
        updated = self.store.get_prompt_version(version_id)
        self.assertEqual(updated["status"], "keep")
        self.assertIsNotNone(updated["decided_at"])

    def test_keep_at_exact_threshold(self):
        version_id = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name="cohort/euphoria_2021/auto/volatility/2021-01-02",
            base_commit_hash="a" * 40,
        )
        self.store.set_version_eval(version_id, 0.5, 0.6, 0.1)  # exactly 0.1
        version = self.store.get_prompt_version(version_id)

        result = decide(self.store, self.git_ops, version, self.config)
        self.assertEqual(result, "keep")

    def test_keep_appends_log(self):
        version_id = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name="cohort/euphoria_2021/auto/volatility/2021-01-03",
            base_commit_hash="a" * 40,
        )
        self.store.set_version_eval(version_id, 0.5, 0.7, 0.2)
        version = self.store.get_prompt_version(version_id)

        decide(self.store, self.git_ops, version, self.config)

        log = self.store.get_log()
        kept_entries = [e for e in log if e["event"] == "kept"]
        self.assertEqual(len(kept_entries), 1)
        self.assertIn("0.2000", kept_entries[0]["detail"])


class TestDecideRevert(unittest.TestCase):
    """Test the revert path (delta < threshold)."""

    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "scorecard.db"
        self.store = ScorecardStore(db_path=self.db_path)
        self.git_ops = MagicMock()
        self.config = {
            "autoresearch": {
                "keep_threshold_delta_sharpe": 0.1,
            }
        }

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_revert_when_delta_below_threshold(self):
        version_id = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name="cohort/euphoria_2021/auto/volatility/2021-01-04",
            base_commit_hash="a" * 40,
        )
        self.store.set_version_eval(version_id, 0.5, 0.55, 0.05)
        version = self.store.get_prompt_version(version_id)

        result = decide(self.store, self.git_ops, version, self.config)

        self.assertEqual(result, "revert")
        self.git_ops.delete_branch.assert_called_once_with(
            "cohort/euphoria_2021/auto/volatility/2021-01-04"
        )
        updated = self.store.get_prompt_version(version_id)
        self.assertEqual(updated["status"], "revert")

    def test_revert_negative_delta(self):
        version_id = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name="cohort/euphoria_2021/auto/volatility/2021-01-05",
            base_commit_hash="a" * 40,
        )
        self.store.set_version_eval(version_id, 0.5, 0.3, -0.2)
        version = self.store.get_prompt_version(version_id)

        result = decide(self.store, self.git_ops, version, self.config)
        self.assertEqual(result, "revert")

    def test_revert_appends_log(self):
        version_id = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name="cohort/euphoria_2021/auto/volatility/2021-01-06",
            base_commit_hash="a" * 40,
        )
        self.store.set_version_eval(version_id, 0.5, 0.55, 0.05)
        version = self.store.get_prompt_version(version_id)

        decide(self.store, self.git_ops, version, self.config)

        log = self.store.get_log()
        reverted_entries = [e for e in log if e["event"] == "reverted"]
        self.assertEqual(len(reverted_entries), 1)
        self.assertIn("0.0500", reverted_entries[0]["detail"])


class TestDecideErrors(unittest.TestCase):
    """Test error paths."""

    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "scorecard.db"
        self.store = ScorecardStore(db_path=self.db_path)
        self.git_ops = MagicMock()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_raises_when_no_delta_sharpe(self):
        version_id = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name="cohort/euphoria_2021/auto/volatility/2021-01-07",
            base_commit_hash="a" * 40,
        )
        version = self.store.get_prompt_version(version_id)

        with self.assertRaises(ValueError) as ctx:
            decide(self.store, self.git_ops, version)
        self.assertIn("no delta_sharpe", str(ctx.exception))

    def test_merge_failure_does_not_prevent_keep_status(self):
        """If merge_to_main raises, the version still gets marked as keep."""
        self.git_ops.merge_to_main.side_effect = RuntimeError("merge conflict")

        version_id = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name="cohort/euphoria_2021/auto/volatility/2021-01-08",
            base_commit_hash="a" * 40,
        )
        self.store.set_version_eval(version_id, 0.5, 0.7, 0.2)
        version = self.store.get_prompt_version(version_id)

        result = decide(self.store, self.git_ops, version)
        self.assertEqual(result, "keep")
        updated = self.store.get_prompt_version(version_id)
        self.assertEqual(updated["status"], "keep")


if __name__ == "__main__":
    unittest.main()
