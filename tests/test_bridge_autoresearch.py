"""Tests for mosaic.bridge.handlers.autoresearch RPC routing (Plan ss11.5 4C/4D)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import unittest
import datetime as _dt
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

# Imported eagerly so the dynamic handler load below (which bypasses the
# handlers __init__) still resolves these without tripping E402.
import mosaic.bridge.protocol  # noqa: F401
from mosaic.bridge.protocol import RpcError
from mosaic.autoresearch.prompt_repo import init_private_prompt_repo
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
autoresearch_historical_decide = _ar.autoresearch_historical_decide
autoresearch_historical_validate = _ar.autoresearch_historical_validate
autoresearch_review_domain_promotion = _ar.autoresearch_review_domain_promotion
autoresearch_get_log = _ar.autoresearch_get_log
autoresearch_list_active_branches = _ar.autoresearch_list_active_branches
autoresearch_prepare_worktree = _ar.autoresearch_prepare_worktree
autoresearch_cleanup_worktree = _ar.autoresearch_cleanup_worktree
autoresearch_gc_worktrees = _ar.autoresearch_gc_worktrees
autoresearch_revert_modification = _ar.autoresearch_revert_modification

# The module path used by patch() -- must match sys.modules key above.
_MOD = "mosaic.bridge.handlers.autoresearch"


def _ntd(d: str, n: int) -> str:
    return (_dt.date.fromisoformat(d) + _dt.timedelta(days=n)).isoformat()


def _ptd(d: str, n: int) -> str:
    return (_dt.date.fromisoformat(d) - _dt.timedelta(days=n)).isoformat()


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

    def test_trigger_creates_version_without_project_branch(self):
        result = autoresearch_trigger({
            "cohort": "euphoria_2021",
            "force_agent": "volatility",
        })
        self.assertIn("version_id", result)
        self.assertEqual(result["agent"], "volatility")
        self.assertIn("cohort/euphoria_2021/auto/volatility/", result["branch_name"])
        self.assertIsInstance(result["base_commit"], str)
        self.assertTrue(len(result["base_commit"]) >= 7)
        git_branch = subprocess.run(
            ["git", "-C", str(self.repo_path), "branch", "--list",
             result["branch_name"]],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(git_branch, "")

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

    def test_historical_trigger_uses_simulated_clock_and_private_prompt_base(self):
        from mosaic.autoresearch.git_ops import GitOps

        prompt_base = GitOps(self.repo_path).current_commit()
        with patch.object(_ar, "_private_git_ops", return_value=GitOps(self.repo_path)):
            result = autoresearch_trigger({
                "cohort": "history_walkforward_2009",
                "force_agent": "volatility",
                "historical_sandbox": True,
                "historical_run_id": "history-test-1",
                "as_of_date": "2011-01-05",
                "base_prompt_commit": prompt_base,
                "code_commit_hash": "c" * 40,
            })

        self.assertEqual(
            result["branch_name"],
            "history/history-test-1/history_walkforward_2009/volatility/2011-01-05",
        )
        self.assertEqual(result["base_commit"], prompt_base)
        version = self.store.get_prompt_version(result["version_id"])
        self.assertTrue(version["created_at"].startswith("2011-01-05T00:00:00"))
        self.assertEqual(version["code_commit_hash"], "c" * 40)

    def test_simulated_clock_requires_historical_sandbox(self):
        with self.assertRaises(RpcError) as ctx:
            autoresearch_trigger({
                "cohort": "euphoria_2021",
                "force_agent": "volatility",
                "historical_run_id": "history-test-1",
                "as_of_date": "2011-01-05",
            })
        self.assertIn("historical_sandbox", ctx.exception.message)


class TestAutoresearchHistoricalDecide(unittest.TestCase):
    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.store = ScorecardStore(db_path=self.tmp / "scorecard.db")
        self._store_patch = patch.object(_ar, "_store", return_value=self.store)
        self._store_patch.start()

    def tearDown(self):
        self._store_patch.stop()
        self._tmpdir.cleanup()

    def test_revert_is_audit_only_and_uses_simulated_decision_date(self):
        vid = self.store.create_prompt_version(
            cohort="history_walkforward_2009",
            agent="volatility",
            branch_name="history/history_walkforward_2009/volatility/2011-01-05",
            base_commit_hash="a" * 40,
        )
        self.store.set_version_mutation(
            vid,
            "b" * 40,
            prompt_repo_id="private",
        )

        result = autoresearch_historical_decide({
            "version_id": vid,
            "decision": "revert",
            "decided_at": "2011-10-10",
            "base_ref": "a" * 40,
        })

        self.assertTrue(result["created"])
        version = self.store.get_prompt_version(vid)
        self.assertEqual(version["status"], "revert")
        self.assertTrue(version["decided_at"].startswith("2011-10-10T00:00:00"))
        events = [entry["event"] for entry in self.store.get_log()]
        self.assertIn("historical_reverted", events)

    def test_historical_validation_is_read_only(self):
        vid = self.store.create_prompt_version(
            cohort="history_walkforward_2009",
            agent="volatility",
            branch_name="history/history-test-1/history_walkforward_2009/volatility/2011-01-05",
            base_commit_hash="a" * 40,
        )
        self.store.set_version_mutation(
            vid,
            "b" * 40,
            prompt_repo_id="private",
        )
        compatibility = {
            "compatible": False,
            "unknown_tools": ["get_future_data"],
            "missing_files": [],
            "dropped_output_sections": [],
        }
        with (
            patch.object(_ar, "_git_ops_for_branch", return_value=object()),
            patch.object(_ar, "_git_ops", return_value=object()),
            patch(
                "mosaic.autoresearch.evaluator.validate_prompt_tool_compatibility",
                return_value=compatibility,
            ),
        ):
            result = autoresearch_historical_validate({"version_id": vid})

        self.assertFalse(result["compatible"])
        self.assertEqual(result["unknown_tools"], ["get_future_data"])
        self.assertEqual(self.store.get_prompt_version(vid)["status"], "pending")

    def test_keep_updates_only_isolated_active_branch_and_is_idempotent(self):
        from mosaic.autoresearch.git_ops import GitOps

        repo = self.tmp / "prompts"
        repo.mkdir()
        _make_git_repo(repo)
        git_ops = GitOps(repo)
        base = git_ops.current_commit()
        candidate_branch = (
            "history/history-test-1/history_walkforward_2009/volatility/2011-01-05"
        )
        prompt_paths = {
            "prompts/mosaic/history_walkforward_2009/macro/volatility.zh.md": "候选\n",
            "prompts/mosaic/history_walkforward_2009/macro/volatility.en.md": "candidate\n",
        }
        candidate_commit = git_ops.write_and_commit(
            prompt_paths,
            message="candidate",
            branch=candidate_branch,
            base_ref=base,
        )
        vid = self.store.create_prompt_version(
            cohort="history_walkforward_2009",
            agent="volatility",
            branch_name=candidate_branch,
            base_commit_hash=base,
        )
        self.store.set_version_mutation(
            vid,
            candidate_commit,
            prompt_repo_id="private",
        )
        active_branch = "history/history_walkforward_2009/active/history-test-1"
        params = {
            "version_id": vid,
            "decision": "keep",
            "decided_at": "2011-10-10",
            "base_ref": base,
            "active_branch": active_branch,
        }

        with patch.object(_ar, "_private_git_ops", return_value=git_ops):
            first = autoresearch_historical_decide(params)
            repeated = autoresearch_historical_decide(params)

        self.assertTrue(first["created"])
        self.assertFalse(repeated["created"])
        self.assertEqual(first["active_commit"], repeated["active_commit"])
        self.assertEqual(git_ops.current_commit(), base)
        for path, content in prompt_paths.items():
            self.assertEqual(git_ops.show_file(active_branch, path), content)

        second_branch = "history/history-test-1/history_walkforward_2009/china/2011-01-05"
        second_paths = {
            "prompts/mosaic/history_walkforward_2009/macro/china.zh.md": "中国候选\n",
            "prompts/mosaic/history_walkforward_2009/macro/china.en.md": "china candidate\n",
        }
        second_commit = git_ops.write_and_commit(
            second_paths,
            message="second candidate",
            branch=second_branch,
            base_ref=base,
        )
        second_vid = self.store.create_prompt_version(
            cohort="history_walkforward_2009",
            agent="china",
            branch_name=second_branch,
            base_commit_hash=base,
        )
        self.store.set_version_mutation(
            second_vid,
            second_commit,
            prompt_repo_id="private",
        )
        with patch.object(_ar, "_private_git_ops", return_value=git_ops):
            second = autoresearch_historical_decide({
                "version_id": second_vid,
                "decision": "keep",
                "decided_at": "2011-10-10",
                "base_ref": first["active_commit"],
                "active_branch": active_branch,
            })

        self.assertNotEqual(second["active_commit"], first["active_commit"])
        for path, content in {**prompt_paths, **second_paths}.items():
            self.assertEqual(git_ops.show_file(active_branch, path), content)


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
            "prompt_repo_id": "private",
            "prompt_base_commit_hash": "d" * 40,
            "prompt_sha256": "f" * 64,
            "code_commit_hash": "a" * 40,
        })
        self.assertTrue(result["ok"])

        v = self.store.get_prompt_version(vid)
        self.assertEqual(v["modification_commit_hash"], "b" * 40)
        self.assertEqual(v["modification_summary"], "improved risk handling")
        self.assertEqual(v["prompt_repo_id"], "private")
        self.assertEqual(v["prompt_base_commit_hash"], "d" * 40)
        self.assertEqual(v["prompt_sha256"], "f" * 64)
        self.assertEqual(v["code_commit_hash"], "a" * 40)

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

    def test_record_domain_mutation_advances_to_validated(self):
        vid = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name="cohort/euphoria_2021/auto/volatility/2021-01-03",
            base_commit_hash="a" * 40,
        )
        metadata = {
            "mutation_id": "KM-domain-1",
            "transaction_id": "TX-KM-domain-1",
            "experiment_id": "EXP-KM-domain-1",
            "mutation_kind": "domain_knob",
            "domain_card_id": "macro.volatility.test",
        }
        params = {
            "version_id": vid,
            "commit_hash": "b" * 40,
            "mutation_metadata": metadata,
        }
        autoresearch_record_mutation(params)
        repeated = autoresearch_record_mutation(params)
        version = self.store.get_prompt_version(vid)
        self.assertEqual(version["mutation_lifecycle"], "validated")
        self.assertEqual(self.store.get_version_mutation_metadata(vid), metadata)
        events = [entry["event"] for entry in self.store.get_log()]
        self.assertEqual(events, ["validated", "proposed"])
        self.assertTrue(repeated["idempotent"])


class TestAutoresearchEvaluatePending(unittest.TestCase):
    """Test autoresearch.evaluate_pending — esp. the version_id scoping (§11.6 O(N²) fix)."""

    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "scorecard.db"
        self.store = ScorecardStore(db_path=self.db_path)
        self._store_patch = patch.object(_ar, "_store", return_value=self.store)
        self._store_patch.start()
        self._compat_patch = patch(
            "mosaic.autoresearch.evaluator.validate_prompt_tool_compatibility",
            return_value={
                "compatible": True,
                "referenced_tools": [],
                "unknown_tools": [],
                "missing_files": [],
            },
        )
        self._compat = self._compat_patch.start()

    def tearDown(self):
        self._compat_patch.stop()
        self._store_patch.stop()
        self._tmpdir.cleanup()

    def _mutated_version(self, branch: str) -> int:
        vid = self.store.create_prompt_version(
            cohort="euphoria_2021", agent="volatility",
            branch_name=branch, base_commit_hash="a" * 40,
        )
        self.store.set_version_mutation(vid, "b" * 40, "x")
        return vid

    def _private_mutated_version(self, branch: str) -> int:
        vid = self.store.create_prompt_version(
            cohort="euphoria_2021", agent="volatility",
            branch_name=branch, base_commit_hash="a" * 40,
        )
        self.store.set_version_mutation(
            vid,
            "b" * 40,
            "x",
            prompt_repo_id="private",
            prompt_base_commit_hash="d" * 40,
            prompt_sha256="f" * 64,
            code_commit_hash="c" * 40,
        )
        return vid

    def _domain_mutated_version(self, branch: str) -> int:
        vid = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name=branch,
            base_commit_hash="a" * 40,
        )
        self.store.set_version_mutation(
            vid,
            "b" * 40,
            "domain mutation",
            mutation_metadata={
                "mutation_id": "KM-domain-1",
                "transaction_id": "TX-KM-domain-1",
                "experiment_id": "EXP-KM-domain-1",
                "mutation_kind": "domain_knob",
                "domain_card_id": "macro.volatility.test",
            },
        )
        self.store.set_version_mutation_lifecycle(vid, "validated")
        return vid

    def _generic_mutated_version(self, branch: str) -> int:
        vid = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name=branch,
            base_commit_hash="a" * 40,
        )
        self.store.set_version_mutation(
            vid,
            "b" * 40,
            "generic mutation",
            mutation_metadata={
                "mutation_id": "KM-generic-1",
                "transaction_id": "TX-KM-generic-1",
                "experiment_id": "EXP-KM-generic-1",
                "mutation_kind": "generic_knob",
                "generic_target_paths": [
                    "/rule_packs/macro.volatility.runtime.v1/rules/"
                    "macro.volatility.soft.001/confidence_policy/"
                    "missing_current_data/cap"
                ],
            },
        )
        self.store.set_version_mutation_lifecycle(vid, "validated")
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
        self.assertEqual(
            [run["kind"] for run in result["results"][0]["missing_runs"]],
            ["base", "mod"],
        )

    def test_domain_mutation_never_falls_back_to_sharpe_only(self):
        vid = self._domain_mutated_version(
            "cohort/euphoria_2021/auto/volatility/2021-01-06"
        )
        with patch("mosaic.autoresearch.evaluator.compute_delta") as compute_delta:
            result = autoresearch_evaluate_pending({"version_id": vid})

        self.assertEqual(result["results"][0]["status"], "needs_fill")
        self.assertTrue(result["results"][0]["missing_domain_samples"])
        self.assertEqual(
            self.store.get_prompt_version(vid)["mutation_lifecycle"], "needs_fill"
        )
        compute_delta.assert_not_called()

    def test_generic_mutation_never_falls_back_to_sharpe_only(self):
        vid = self._generic_mutated_version(
            "cohort/euphoria_2021/auto/volatility/2021-01-07"
        )
        with patch("mosaic.autoresearch.evaluator.compute_delta") as compute_delta:
            result = autoresearch_evaluate_pending({"version_id": vid})

        self.assertEqual(result["results"][0]["status"], "needs_fill")
        self.assertTrue(result["results"][0]["missing_paired_samples"])
        self.assertEqual(
            self.store.get_prompt_version(vid)["mutation_lifecycle"], "needs_fill"
        )
        compute_delta.assert_not_called()

    def test_domain_promotion_requires_operator_and_closed_holdout_evidence(self):
        vid = self.store.create_prompt_version(
            cohort="euphoria_2021",
            agent="volatility",
            branch_name="cohort/euphoria_2021/auto/volatility/2021-01-08",
            base_commit_hash="a" * 40,
        )
        metadata = {
            "mutation_id": "KM-domain-promote",
            "transaction_id": "TX-KM-domain-promote",
            "transaction_manifest_hash": f"sha256:{'1' * 64}",
            "experiment_id": "EXP-KM-domain-promote",
            "mutation_kind": "domain_knob",
        }
        self.store.set_version_mutation(
            vid,
            "b" * 40,
            "domain mutation",
            prompt_repo_id="private",
            prompt_sha256="f" * 64,
            code_commit_hash="c" * 40,
            mutation_metadata=metadata,
        )
        self.store.set_version_mutation_lifecycle(vid, "validated")
        self.store.set_version_mutation_lifecycle(vid, "shadow_evaluating")
        self.store.set_version_mutation_lifecycle(vid, "eligible_for_promotion")
        holdout_id = f"sha256:{'2' * 64}"
        result_hash = f"sha256:{'3' * 64}"
        evaluation = {
            "schema_version": "domain_evaluation_result_v1",
            "mutation_id": metadata["mutation_id"],
            "status": "eligible_for_promotion",
            "result_hash": result_hash,
            "pit_audit_hash": f"sha256:{'4' * 64}",
            "holdout_id": holdout_id,
            "holdout_consumption_required": True,
        }
        self.store.set_domain_evaluation_result(vid, evaluation)
        self.store.consume_domain_holdout(
            vid,
            holdout_id=holdout_id,
            mutation_id=metadata["mutation_id"],
            result_hash=result_hash,
        )
        params = {
            "version_id": vid,
            "decision": "keep",
            "approved_by": "operator:test",
            "approval_policy_id": "domain_release_manual_v1",
            "review_reason": "PIT holdout and operational guardrails passed.",
        }

        with patch.dict(
            os.environ,
            {"MOSAIC_PROMPT_RELEASE_AUTHORIZED_OPERATORS": "operator:test"},
        ):
            result = autoresearch_review_domain_promotion(params)
            repeated = autoresearch_review_domain_promotion(params)
            rejected = {**params, "approved_by": "operator:unlisted"}
            with self.assertRaises(RpcError):
                autoresearch_review_domain_promotion(rejected)

        self.assertEqual(result["status"], "kept")
        self.assertTrue(result["created"])
        self.assertFalse(repeated["created"])
        self.assertEqual(self.store.get_prompt_version(vid)["status"], "keep")
        self.assertEqual(
            self.store.get_domain_promotion_decision(vid)["approved_by"],
            "operator:test",
        )

    def test_needs_fill_reports_private_prompt_metadata(self):
        class FakePrivateGit:
            def branch_exists(self, _branch: str) -> bool:
                return True

        vid = self._private_mutated_version(
            "cohort/euphoria_2021/auto/volatility/2021-01-04"
        )

        with patch.object(_ar, "_private_git_ops", return_value=FakePrivateGit()):
            result = autoresearch_evaluate_pending({"version_id": vid})

        self.assertEqual(result["results"][0]["status"], "needs_fill")
        mod_spec = [
            run for run in result["results"][0]["missing_runs"]
            if run["kind"] == "mod"
        ][0]
        self.assertEqual(mod_spec["prompt_commit_hash"], "b" * 40)
        self.assertEqual(mod_spec["prompt_repo_id"], "private")
        self.assertEqual(mod_spec["prompt_sha256"], "f" * 64)
        self.assertEqual(mod_spec["code_commit_hash"], "c" * 40)
        self.assertEqual(mod_spec["private_prompt_commit"], "b" * 40)

    def test_private_version_requires_private_repo_git(self):
        vid = self._private_mutated_version(
            "cohort/euphoria_2021/auto/volatility/2021-01-05"
        )

        with self.assertRaises(RpcError) as ctx:
            autoresearch_evaluate_pending({"version_id": vid})

        self.assertIn("MOSAIC_PROMPTS_REPO", ctx.exception.message)

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

    def test_incompatible_prompt_is_recorded_and_skips_fill(self):
        self._compat.return_value = {
            "compatible": False,
            "referenced_tools": ["get_removed_tool"],
            "unknown_tools": ["get_removed_tool"],
            "missing_files": [],
        }
        vid = self._mutated_version("cohort/euphoria_2021/auto/volatility/2021-01-03")

        result = autoresearch_evaluate_pending({"version_id": vid})

        self.assertEqual(result["results"][0]["status"], "incompatible")
        self.assertIn("get_removed_tool", result["results"][0]["detail"])
        version = self.store.get_prompt_version(vid)
        self.assertEqual(version["status"], "incompatible")
        log = self.store.get_log()
        self.assertEqual(log[0]["event"], "incompatible")


class TestMacroAutoresearchIntegration(unittest.TestCase):
    """P6 cross-phase macro path: score → select → mutate → evaluate by Sharpe."""

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
        self._compat_patch = patch(
            "mosaic.autoresearch.evaluator.validate_prompt_tool_compatibility",
            return_value={
                "compatible": True,
                "referenced_tools": [],
                "unknown_tools": [],
                "missing_files": [],
            },
        )
        self._store_patch.start()
        self._repo_patch.start()
        self._compat_patch.start()

    def tearDown(self):
        self._compat_patch.stop()
        self._repo_patch.stop()
        self._store_patch.stop()
        self._tmpdir.cleanup()

    def test_macro_private_mutation_kept_by_portfolio_delta_not_macro_hit_rate(self):
        from datetime import datetime, timezone

        from mosaic.scorecard.scorer import MacroScorer

        d0 = "2024-01-02"
        t5 = _ntd(d0, 5)
        state = {
            "active_cohort": "euphoria_2021",
            "as_of_date": d0,
            "prompt_repo_id": "private",
            "prompt_sha256": "f" * 64,
            "layer1_outputs": {
                "volatility": {
                    "agent": "volatility",
                    "regime_filter": "RISK_ON",
                    "confidence": 0.8,
                }
            },
            "layer1_consensus": {"stance": "BULLISH", "confidence": 0.8},
        }
        self.assertEqual(self.store.append_macro_signals_from_state(state), 1)

        closes = {d0: 100.0, t5: 97.0}
        with patch.multiple(
            "mosaic.dataflows.calendar",
            next_trading_day=_ntd,
            previous_trading_day=_ptd,
        ), patch(
            "mosaic.scorecard.scorer._fetch_close",
            lambda _ts, date: closes.get(date),
        ), patch(
            "mosaic.scorecard.scorer._fetch_benchmark_series",
            lambda *_args: [100.0, 99.0, 98.0, 97.0],
        ):
            MacroScorer(
                self.store,
                benchmark="000300.SH",
                agent_specific_labels_enabled=False,
            ).score_pending("euphoria_2021", "2024-01-10")

        with self.store._connect() as conn:
            scored = conn.execute(
                "SELECT hit_5d, raw_macro_score_5d, prompt_repo_id, prompt_sha256 "
                "FROM macro_signals"
            ).fetchone()
        self.assertEqual(scored["hit_5d"], 0)
        self.assertLess(scored["raw_macro_score_5d"], 0)
        self.assertEqual(scored["prompt_repo_id"], "private")
        self.assertEqual(scored["prompt_sha256"], "f" * 64)

        now = datetime(2024, 3, 1, 12, 0, tzinfo=timezone.utc)
        with patch.object(_ar, "_now", return_value=now):
            triggered = autoresearch_trigger({"cohort": "euphoria_2021"})
        self.assertEqual(triggered["agent"], "volatility")

        autoresearch_record_mutation(
            {
                "version_id": triggered["version_id"],
                "commit_hash": "b" * 40,
                "summary": "macro risk-on calibration",
                "prompt_repo_id": "private",
                "prompt_base_commit_hash": "d" * 40,
                "prompt_sha256": "f" * 64,
                "code_commit_hash": "c" * 40,
            }
        )
        version = self.store.get_prompt_version(triggered["version_id"])
        self.assertEqual(version["prompt_repo_id"], "private")
        self.assertEqual(version["prompt_sha256"], "f" * 64)

        start, end = "2020-07-01", "2021-02-18"
        base_run = self.store.create_backtest_run(
            cohort="euphoria_2021",
            start_date=start,
            end_date=end,
            prompt_commit_hash=version["base_commit_hash"],
        )
        wrong_repo_mod_run = self.store.create_backtest_run(
            cohort="euphoria_2021",
            start_date=start,
            end_date=end,
            prompt_commit_hash="b" * 40,
            prompt_repo_id="project",
            prompt_sha256="0" * 64,
            code_commit_hash="c" * 40,
        )
        private_mod_run = self.store.create_backtest_run(
            cohort="euphoria_2021",
            start_date=start,
            end_date=end,
            prompt_commit_hash="b" * 40,
            prompt_repo_id="private",
            prompt_sha256="f" * 64,
            code_commit_hash="c" * 40,
        )
        for run_id in (base_run, wrong_repo_mod_run, private_mod_run):
            self.store.complete_backtest_run(run_id)

        seen_run_ids = []

        def fake_find_run_sharpe(_store, run_id):
            seen_run_ids.append(run_id)
            if run_id == base_run:
                return 1.0
            if run_id == private_mod_run:
                return 1.25
            if run_id == wrong_repo_mod_run:
                return 9.0
            return None

        class FakePrivateGit:
            def branch_exists(self, _branch: str) -> bool:
                return True

            def merge_to_main(self, _branch: str) -> None:
                return None

            def delete_branch(self, _branch: str) -> None:
                return None

        with patch.object(_ar, "_private_git_ops", return_value=FakePrivateGit()), \
             patch("mosaic.autoresearch.evaluator._find_run_sharpe", fake_find_run_sharpe):
            result = autoresearch_evaluate_pending({"version_id": triggered["version_id"]})

        self.assertEqual(result["results"][0]["status"], "kept")
        self.assertAlmostEqual(result["results"][0]["delta_sharpe"], 0.25)
        self.assertIn(private_mod_run, seen_run_ids)
        self.assertNotIn(wrong_repo_mod_run, seen_run_ids)
        self.assertEqual(self.store.get_prompt_version(triggered["version_id"])["status"], "keep")


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
        self.assertEqual(result["repo_target"], "project_git")
        wt_path = Path(result["path"])
        self.assertTrue(wt_path.exists())

        cleanup_result = autoresearch_cleanup_worktree({"path": result["path"]})
        self.assertTrue(cleanup_result["ok"])

    def test_prepare_worktree_invalid_branch(self):
        with self.assertRaises(RpcError):
            autoresearch_prepare_worktree({"branch": ""})

    def test_prepare_private_prompt_worktree_returns_prompts_root(self):
        private_repo = self.tmp / "private-prompts"
        init_private_prompt_repo(private_repo, project_root=self.repo_path)
        with patch.dict(os.environ, {"MOSAIC_PRIVATE_PROMPT_REPO": str(private_repo)}):
            result = autoresearch_prepare_worktree({
                "repo_target": "private_git",
                "ref": "main",
            })

            self.assertEqual(result["repo_target"], "private_git")
            wt_path = Path(result["path"])
            prompts_root = Path(result["prompts_root"])
            self.assertTrue(wt_path.exists())
            self.assertEqual(prompts_root, wt_path / "prompts" / "mosaic")
            self.assertTrue(prompts_root.exists())

            cleanup_result = autoresearch_cleanup_worktree({
                "path": result["path"],
                "repo_target": "private_git",
            })
            self.assertTrue(cleanup_result["ok"])

    def test_gc_worktrees_reports_project_repo(self):
        result = autoresearch_gc_worktrees({
            "repo_target": "project_git",
            "max_age_hours": 0,
        })

        self.assertEqual(result["results"][0]["repo_target"], "project_git")
        self.assertIn("removed", result["results"][0])


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
