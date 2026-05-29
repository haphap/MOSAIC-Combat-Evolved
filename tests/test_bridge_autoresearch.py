"""Tests for mosaic.bridge.handlers.autoresearch RPC routing (Plan ss11.5 4C/4D)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

# Imported eagerly so the dynamic handler load below (which bypasses the
# handlers __init__) still resolves these without tripping E402.
import mosaic.bridge.protocol  # noqa: F401
from mosaic.bridge.protocol import RpcError
from mosaic.scorecard.store import ScorecardStore

# Import the autoresearch handler. Prefer the normal package import (which
# registers the @method handlers exactly once); only fall back to an isolated
# module exec when the package __init__ can't be imported (e.g. langchain_core
# missing in an offline sandbox). Re-exec'ing after a successful package import
# would double-register the RPC methods and raise.
try:
    from mosaic.bridge.handlers import autoresearch as _ar
except Exception:
    # The package __init__ imports autoresearch before tools (which needs
    # langchain_core); when tools fails, autoresearch is already in sys.modules
    # AND its @method decorators already ran. Re-exec'ing would double-register,
    # so prefer the partially-imported-but-registered module.
    _key = "mosaic.bridge.handlers.autoresearch"
    if _key in sys.modules:
        _ar = sys.modules[_key]
    else:
        _HANDLER_PATH = (
            Path(__file__).resolve().parent.parent
            / "mosaic" / "bridge" / "handlers" / "autoresearch.py"
        )
        _spec = importlib.util.spec_from_file_location(_key, str(_HANDLER_PATH))
        _ar = importlib.util.module_from_spec(_spec)
        sys.modules[_key] = _ar
        _spec.loader.exec_module(_ar)

# Module-level references to handler functions.
autoresearch_trigger = _ar.autoresearch_trigger
autoresearch_record_mutation = _ar.autoresearch_record_mutation
autoresearch_evaluate_pending = _ar.autoresearch_evaluate_pending
autoresearch_get_log = _ar.autoresearch_get_log
autoresearch_list_active_branches = _ar.autoresearch_list_active_branches
autoresearch_prepare_worktree = _ar.autoresearch_prepare_worktree
autoresearch_cleanup_worktree = _ar.autoresearch_cleanup_worktree
autoresearch_revert_modification = _ar.autoresearch_revert_modification

# The module path used by patch() -- must match sys.modules key above.
_MOD = "mosaic.bridge.handlers.autoresearch"


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


class TestAutoresearchTrigger(unittest.TestCase):
    """Test autoresearch.trigger RPC handler."""

    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.db_path = self.tmp / "scorecard.db"
        self.repo_path = self.tmp / "repo"
        self.repo_path.mkdir()
        _make_git_repo(self.repo_path)

        self.store = ScorecardStore(db_path=self.db_path)
        self._store_patch = patch.object(_ar, "_store", return_value=self.store)
        self._repo_patch = patch.object(_ar, "_repo_root", return_value=self.repo_path)
        self._store_patch.start()
        self._repo_patch.start()

    def tearDown(self):
        self._store_patch.stop()
        self._repo_patch.stop()
        self._tmpdir.cleanup()

    def test_trigger_creates_version_and_branch(self):
        result = autoresearch_trigger({
            "cohort": "euphoria_2021",
            "force_agent": "volatility",
        })
        self.assertIn("version_id", result)
        self.assertEqual(result["agent"], "volatility")
        self.assertIn("cohort/euphoria_2021/auto/volatility/", result["branch_name"])
        self.assertIsInstance(result["base_commit"], str)
        self.assertTrue(len(result["base_commit"]) >= 7)

    def test_trigger_idempotent(self):
        """Calling trigger twice for the same date/agent returns the same version."""
        r1 = autoresearch_trigger({
            "cohort": "euphoria_2021",
            "force_agent": "volatility",
        })
        r2 = autoresearch_trigger({
            "cohort": "euphoria_2021",
            "force_agent": "volatility",
        })
        self.assertEqual(r1["version_id"], r2["version_id"])

    def test_trigger_rejects_invalid_params(self):
        with self.assertRaises(RpcError) as ctx:
            autoresearch_trigger({"cohort": ""})
        self.assertIn("non-empty", ctx.exception.message)

    def test_trigger_dry_run_has_no_side_effects(self):
        """dry_run selects the agent but creates no branch and no version row."""
        result = autoresearch_trigger({
            "cohort": "euphoria_2021",
            "force_agent": "volatility",
            "dry_run": True,
        })
        self.assertIsNone(result["version_id"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["agent"], "volatility")
        # No prompt_versions row persisted.
        self.assertEqual(len(self.store.list_prompt_versions()), 0)
        # No git branch created.
        git_branch = subprocess.run(
            ["git", "-C", str(self.repo_path), "branch", "--list",
             result["branch_name"]],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(git_branch, "")


class TestAutoresearchRecordMutation(unittest.TestCase):
    """Test autoresearch.record_mutation RPC handler."""

    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "scorecard.db"
        self.store = ScorecardStore(db_path=self.db_path)
        self._store_patch = patch.object(_ar, "_store", return_value=self.store)
        self._store_patch.start()

    def tearDown(self):
        self._store_patch.stop()
        self._tmpdir.cleanup()

    def test_record_mutation_updates_version(self):
        vid = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name="cohort/euphoria_2021/auto/volatility/2021-01-01",
            base_commit_hash="a" * 40,
        )
        result = autoresearch_record_mutation({
            "version_id": vid,
            "commit_hash": "b" * 40,
            "summary": "improved risk handling",
        })
        self.assertTrue(result["ok"])

        v = self.store.get_prompt_version(vid)
        self.assertEqual(v["modification_commit_hash"], "b" * 40)
        self.assertEqual(v["modification_summary"], "improved risk handling")

    def test_record_mutation_appends_log(self):
        vid = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name="cohort/euphoria_2021/auto/volatility/2021-01-02",
            base_commit_hash="a" * 40,
        )
        autoresearch_record_mutation({
            "version_id": vid,
            "commit_hash": "c" * 40,
        })
        log = self.store.get_log()
        mutated_entries = [e for e in log if e["event"] == "mutated"]
        self.assertEqual(len(mutated_entries), 1)


class TestAutoresearchEvaluatePending(unittest.TestCase):
    """Test autoresearch.evaluate_pending — esp. the version_id scoping (§11.6 O(N²) fix)."""

    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "scorecard.db"
        self.store = ScorecardStore(db_path=self.db_path)
        self._store_patch = patch.object(_ar, "_store", return_value=self.store)
        self._store_patch.start()

    def tearDown(self):
        self._store_patch.stop()
        self._tmpdir.cleanup()

    def _mutated_version(self, branch: str) -> int:
        vid = self.store.create_prompt_version(
            cohort="euphoria_2021", agent="volatility",
            branch_name=branch, base_commit_hash="a" * 40,
        )
        self.store.set_version_mutation(vid, "b" * 40, "x")
        return vid

    def test_version_id_scopes_to_one_version(self):
        # Two mutated pending versions; ask for just the second.
        self._mutated_version("cohort/euphoria_2021/auto/volatility/2021-01-01")
        vid2 = self._mutated_version("cohort/euphoria_2021/auto/cro/2021-01-01")
        result = autoresearch_evaluate_pending({"version_id": vid2})
        ids = [r["version_id"] for r in result["results"]]
        self.assertEqual(ids, [vid2])
        # No backtest runs exist → needs_fill (proves it reached evaluation).
        self.assertEqual(result["results"][0]["status"], "needs_fill")

    def test_scan_all_without_version_id(self):
        self._mutated_version("cohort/euphoria_2021/auto/volatility/2021-01-01")
        self._mutated_version("cohort/euphoria_2021/auto/cro/2021-01-01")
        result = autoresearch_evaluate_pending({"cohort": "euphoria_2021"})
        self.assertEqual(len(result["results"]), 2)

    def test_unknown_version_id_returns_empty(self):
        result = autoresearch_evaluate_pending({"version_id": 99999})
        self.assertEqual(result["results"], [])

    def test_version_id_must_be_int(self):
        with self.assertRaises(RpcError):
            autoresearch_evaluate_pending({"version_id": "nope"})


class TestAutoresearchGetLog(unittest.TestCase):
    """Test autoresearch.get_log RPC handler."""

    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "scorecard.db"
        self.store = ScorecardStore(db_path=self.db_path)
        self._store_patch = patch.object(_ar, "_store", return_value=self.store)
        self._store_patch.start()

    def tearDown(self):
        self._store_patch.stop()
        self._tmpdir.cleanup()

    def test_get_log_empty(self):
        result = autoresearch_get_log({})
        self.assertEqual(result["entries"], [])

    def test_get_log_with_entries(self):
        vid = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name="test-branch",
            base_commit_hash="a" * 40,
        )
        self.store.append_log(vid, "triggered", "test entry")
        result = autoresearch_get_log({})
        self.assertEqual(len(result["entries"]), 1)
        self.assertEqual(result["entries"][0]["event"], "triggered")

    def test_get_log_cohort_filter(self):
        vid = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name="test-branch-filter",
            base_commit_hash="a" * 40,
        )
        self.store.append_log(vid, "triggered", "test")
        result = autoresearch_get_log({"cohort": "crisis_2008"})
        self.assertEqual(len(result["entries"]), 0)


class TestAutoresearchListActiveBranches(unittest.TestCase):
    """Test autoresearch.list_active_branches RPC handler."""

    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "scorecard.db"
        self.store = ScorecardStore(db_path=self.db_path)
        self._store_patch = patch.object(_ar, "_store", return_value=self.store)
        self._store_patch.start()

    def tearDown(self):
        self._store_patch.stop()
        self._tmpdir.cleanup()

    def test_empty_when_no_pending(self):
        result = autoresearch_list_active_branches({})
        self.assertEqual(result["branches"], [])

    def test_lists_pending_versions(self):
        self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name="cohort/euphoria_2021/auto/volatility/2021-01-01",
            base_commit_hash="a" * 40,
        )
        result = autoresearch_list_active_branches({})
        self.assertEqual(len(result["branches"]), 1)
        self.assertEqual(result["branches"][0]["agent"], "volatility")


class TestAutoresearchWorktree(unittest.TestCase):
    """Test prepare/cleanup_worktree RPC handlers."""

    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.repo_path = self.tmp / "repo"
        self.repo_path.mkdir()
        _make_git_repo(self.repo_path)

        self._repo_patch = patch.object(_ar, "_repo_root", return_value=self.repo_path)
        self._repo_patch.start()

    def tearDown(self):
        self._repo_patch.stop()
        self._tmpdir.cleanup()

    def test_prepare_and_cleanup_worktree(self):
        result = autoresearch_prepare_worktree({"branch": "main"})
        self.assertIn("path", result)
        wt_path = Path(result["path"])
        self.assertTrue(wt_path.exists())

        cleanup_result = autoresearch_cleanup_worktree({"path": result["path"]})
        self.assertTrue(cleanup_result["ok"])

    def test_prepare_worktree_invalid_branch(self):
        with self.assertRaises(RpcError):
            autoresearch_prepare_worktree({"branch": ""})


class TestAutoresearchRevertModification(unittest.TestCase):
    """Test autoresearch.revert_modification RPC handler."""

    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.db_path = self.tmp / "scorecard.db"
        self.repo_path = self.tmp / "repo"
        self.repo_path.mkdir()
        _make_git_repo(self.repo_path)

        self.store = ScorecardStore(db_path=self.db_path)
        self._store_patch = patch.object(_ar, "_store", return_value=self.store)
        self._repo_patch = patch.object(_ar, "_repo_root", return_value=self.repo_path)
        self._store_patch.start()
        self._repo_patch.start()

    def tearDown(self):
        self._store_patch.stop()
        self._repo_patch.stop()
        self._tmpdir.cleanup()

    def test_revert_pending_version(self):
        vid = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name="cohort/euphoria_2021/auto/volatility/2021-01-01",
            base_commit_hash="a" * 40,
        )
        result = autoresearch_revert_modification({"version_id": vid})
        self.assertTrue(result["ok"])
        updated = self.store.get_prompt_version(vid)
        self.assertEqual(updated["status"], "revert")

    def test_revert_kept_within_lockout_blocked(self):
        """A recently kept version cannot be reverted within lockout period."""
        from datetime import datetime, timezone

        vid = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name="cohort/euphoria_2021/auto/volatility/2021-01-02",
            base_commit_hash="a" * 40,
        )
        # Decide as keep just now.
        now_str = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.store.decide_version(vid, "keep", decided_at=now_str)

        with self.assertRaises(RpcError) as ctx:
            autoresearch_revert_modification({"version_id": vid})
        self.assertIn("lockout", ctx.exception.message)

    def test_revert_nonexistent_version_fails(self):
        with self.assertRaises(RpcError) as ctx:
            autoresearch_revert_modification({"version_id": 9999})
        self.assertIn("not found", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
