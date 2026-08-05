"""Tests for the read-only legacy autoresearch boundary."""

from __future__ import annotations

import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import pytest

from mosaic.bridge.handlers import autoresearch as handlers
from mosaic.bridge.protocol import RpcError
from mosaic.bridge.registry import all_methods


RETIRED_METHODS = {
    "autoresearch.trigger",
    "autoresearch.record_mutation",
    "autoresearch.evaluate_pending",
    "autoresearch.historical_validate",
    "autoresearch.historical_decide",
    "autoresearch.review_domain_promotion",
    "autoresearch.revert_modification",
}


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


def test_retired_prompt_writer_rpc_and_symbols_are_absent() -> None:
    assert RETIRED_METHODS.isdisjoint(all_methods())
    for method_name in RETIRED_METHODS:
        symbol = method_name.replace(".", "_")
        assert not hasattr(handlers, symbol)


def test_historical_queries_are_read_only_delegations() -> None:
    store = Mock()
    store.get_log.return_value = [{"id": 1}]
    store.list_active_branches.return_value = [{"id": 2}]
    with patch.object(handlers, "_store", return_value=store):
        assert handlers.autoresearch_get_log({"cohort": "cohort_default", "days": 7}) == {
            "entries": [{"id": 1}]
        }
        assert handlers.autoresearch_list_active_branches(
            {"cohort": "cohort_default"}
        ) == {"branches": [{"id": 2}]}
    store.get_log.assert_called_once_with(cohort="cohort_default", days=7)
    store.list_active_branches.assert_called_once_with(cohort="cohort_default")


@pytest.mark.parametrize("params", [{"days": 0}, {"days": True}, {"cohort": 1}])
def test_historical_query_validation(params: dict[str, object]) -> None:
    with pytest.raises(RpcError):
        handlers.autoresearch_get_log(params)


def test_project_worktree_lifecycle_remains_available() -> None:
    with TemporaryDirectory() as directory:
        repo = Path(directory) / "repo"
        repo.mkdir()
        _make_git_repo(repo)
        with patch.object(handlers, "_repo_root", return_value=repo):
            prepared = handlers.autoresearch_prepare_worktree({"ref": "main"})
            assert Path(prepared["path"]).is_dir()
            assert prepared["repo_target"] == "project_git"
            assert handlers.autoresearch_cleanup_worktree(
                {"path": prepared["path"]}
            ) == {"ok": True}


def test_worktree_gc_rejects_invalid_age() -> None:
    with pytest.raises(RpcError):
        handlers.autoresearch_gc_worktrees({"max_age_hours": -1})
