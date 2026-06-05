from __future__ import annotations

from pathlib import Path

from mosaic.dataflows import china_policy_db
from mosaic.dataflows.exceptions import DataVendorUnavailable


def test_ensure_local_repo_clones_missing_configured_dir(tmp_path, monkeypatch):
    root = tmp_path / "china-policy-db"
    calls: list[tuple[list[str], Path | None]] = []
    monkeypatch.setenv("MOSAIC_CHINA_POLICY_DB_DIR", str(root))
    monkeypatch.setenv("MOSAIC_CHINA_POLICY_DB_REPO_URL", "https://example.test/policy.git")
    monkeypatch.setenv("MOSAIC_CHINA_POLICY_DB_AUTO_SYNC", "1")

    def fake_run_git(args: list[str], *, cwd: Path | None = None) -> str:
        calls.append((args, cwd))
        if args[:2] == ["clone", "--depth=1"]:
            clone_root = Path(args[-1])
            clone_root.mkdir(parents=True)
            (clone_root / ".git").mkdir()
        return ""

    monkeypatch.setattr(china_policy_db, "_run_git", fake_run_git)

    found = china_policy_db.ensure_local_repo()

    assert found == (root, str(root))
    assert calls == [
        (["clone", "--depth=1", "https://example.test/policy.git", str(root)], None)
    ]
    assert (root / ".git" / "mosaic-sync.json").is_file()


def test_ensure_local_repo_aborts_wedged_rebase_after_pull_failure(tmp_path, monkeypatch):
    root = tmp_path / "china-policy-db"
    (root / ".git").mkdir(parents=True)
    calls: list[list[str]] = []
    monkeypatch.setenv("MOSAIC_CHINA_POLICY_DB_DIR", str(root))
    monkeypatch.setenv("MOSAIC_CHINA_POLICY_DB_AUTO_SYNC", "1")

    def fake_run_git(args: list[str], *, cwd: Path | None = None) -> str:
        assert cwd == root
        calls.append(args)
        if args == ["pull", "--rebase", "--autostash"]:
            raise DataVendorUnavailable("conflicting rebase")
        return ""

    monkeypatch.setattr(china_policy_db, "_run_git", fake_run_git)

    found = china_policy_db.ensure_local_repo()

    assert found == (root, str(root))
    assert calls == [
        ["pull", "--rebase", "--autostash"],
        ["rebase", "--abort"],
    ]


def test_commit_skips_local_commit_when_push_is_off(tmp_path, monkeypatch):
    root = tmp_path / "china-policy-db"
    (root / ".git").mkdir(parents=True)
    calls: list[list[str]] = []
    monkeypatch.setenv("MOSAIC_CHINA_POLICY_DB_PUSH_UPDATES", "0")

    def fake_run_git(args: list[str], *, cwd: Path | None = None) -> str:
        assert cwd == root
        calls.append(args)
        if args[:3] == ["status", "--porcelain", "--"]:
            return " M data/pboc_ops/parsed/articles.jsonl\n"
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(china_policy_db, "_run_git", fake_run_git)

    result = china_policy_db.commit_and_maybe_push_updates(
        root,
        ["data/pboc_ops"],
        message="Update PBOC open-market data",
    )

    assert result["changed"] is True
    assert result["skipped_commit"] is True
    assert result["committed"] is False
    assert result["pushed"] is False
    assert calls == [["status", "--porcelain", "--", "data/pboc_ops"]]


def test_commit_unshallows_before_push(tmp_path, monkeypatch):
    root = tmp_path / "china-policy-db"
    (root / ".git").mkdir(parents=True)
    calls: list[list[str]] = []
    monkeypatch.setenv("MOSAIC_CHINA_POLICY_DB_PUSH_UPDATES", "1")

    def fake_run_git(args: list[str], *, cwd: Path | None = None) -> str:
        assert cwd == root
        calls.append(args)
        if args[:3] == ["status", "--porcelain", "--"]:
            return " M data/gov_policy/parsed/policy_documents.jsonl\n"
        if args == ["rev-parse", "--is-shallow-repository"]:
            return "true\n"
        if args[:4] == ["diff", "--cached", "--name-only", "--"]:
            return "data/gov_policy/parsed/policy_documents.jsonl\n"
        return ""

    monkeypatch.setattr(china_policy_db, "_run_git", fake_run_git)

    result = china_policy_db.commit_and_maybe_push_updates(
        root,
        ["data/gov_policy"],
        message="Update gov.cn policy data",
    )

    assert result["committed"] is True
    assert result["pushed"] is True
    assert ["fetch", "--unshallow"] in calls
    assert calls.index(["fetch", "--unshallow"]) < calls.index(["push"])
