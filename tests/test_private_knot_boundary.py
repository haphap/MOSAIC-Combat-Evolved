from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import check_private_knot_boundary


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _content_boundary_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    public_root = tmp_path / "public"
    private_root = tmp_path / "private"
    public_root.mkdir()
    (private_root / "registry/knot").mkdir(parents=True)
    (private_root / "prompts/mosaic/cohort_default/macro").mkdir(parents=True)
    (private_root / "registry/knot/prompt_parameter_contract_v1.json").write_text(
        json.dumps(
            {
                "parameters": [
                    {
                        "parameterId": "china.private_prompt_signal",
                        "disposition": "PROMPT_KNOT",
                    },
                    {
                        "parameterId": "risk.public_deterministic_policy",
                        "disposition": "DETERMINISTIC_ACTIVE",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (private_root / "prompts/mosaic/cohort_default/macro/china.zh.md").write_text(
        "<!-- cohort-behavior:start -->\n"
        "保持中国观察镜头。\n判断校准：仅供私有候选使用的完整校准句子；"
        "第二段私有校准内容不得对外公开。\n"
        "<!-- cohort-behavior:end -->\n",
        encoding="utf-8",
    )
    tracked = public_root / "tracked.txt"
    tracked.write_text("ordinary public text\n", encoding="utf-8")
    _git(public_root, "init", "-q")
    _git(public_root, "add", "tracked.txt")
    return public_root, private_root, tracked


def test_public_boundary_uses_knot_free_runtime_v5(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOSAIC_PROMPTS_REPO", raising=False)
    monkeypatch.delenv("MOSAIC_PRIVATE_PROMPT_REPO", raising=False)

    check_private_knot_boundary.check(require_private=False)

    runtime = json.loads(
        check_private_knot_boundary.RUNTIME_AGENT_MANIFEST_PATH.read_text(
            encoding="utf-8"
        )
    )
    assert runtime["schema_version"] == "runtime_agent_manifest_v5"
    assert "knot" not in json.dumps(runtime).lower()


def test_execution_release_boundary_accepts_only_execution_only_v4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_root = tmp_path / "registry/prompt_checks/execution_behavior_releases"
    archive_root.mkdir(parents=True)
    release_content = {
        "schema_version": "execution_behavior_release_manifest_v4",
        "provider_binding": {"provider": "fixture"},
        "active_production_variants": [{"index": index} for index in range(16)],
        "execution_contracts": [{"index": index} for index in range(54)],
    }
    release_id = (
        "execution-behavior-release:"
        + check_private_knot_boundary.canonical_hash(release_content).removeprefix(
            "sha256:"
        )
    )
    with_id = {
        "schema_version": release_content["schema_version"],
        "execution_behavior_release_id": release_id,
        "provider_binding": release_content["provider_binding"],
        "active_production_variants": release_content["active_production_variants"],
        "execution_contracts": release_content["execution_contracts"],
    }
    release_hash = check_private_knot_boundary.canonical_hash(with_id)
    archive_ref = (
        "registry/prompt_checks/execution_behavior_releases/"
        f"{release_id.removeprefix('execution-behavior-release:')}--"
        f"{release_hash.removeprefix('sha256:')}.json"
    )
    archive_path = tmp_path / archive_ref
    release = {**with_id, "execution_behavior_release_hash": release_hash}
    archive_path.write_text(json.dumps(release), encoding="utf-8")
    contract_ref = tmp_path / "registry/prompt_checks/prompt_release_contract_ref_v2.json"
    contract_ref.write_text(
        json.dumps(
            {
                "schema_version": "prompt_release_contract_ref_v2",
                "sources": {
                    "execution_behavior_release_archive": {
                        "path": archive_ref,
                        "release_id": release_id,
                        "release_hash": release_hash,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(check_private_knot_boundary, "ROOT", tmp_path)
    monkeypatch.setattr(
        check_private_knot_boundary, "PROMPT_RELEASE_CONTRACT_REF_PATH", contract_ref
    )
    monkeypatch.setattr(
        check_private_knot_boundary,
        "EXECUTION_RELEASE_ARCHIVE_ROOT",
        archive_root,
    )

    assert check_private_knot_boundary._check_execution_release() == {
        "archive_ref": archive_ref,
        "release_id": release_id,
        "release_hash": release_hash,
    }
    archive_path.write_text(
        json.dumps(
            {
                **release,
                "schema_version": "execution_behavior_release_manifest_v3",
                "private_prompt_commit": "a" * 40,
                "private_prompt_bootstrap": {},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="archive identity mismatch"):
        check_private_knot_boundary._check_execution_release()


@pytest.mark.parametrize(
    "source_commits",
    [None, {}, {"private": "short", "bundled": "b" * 40}],
)
def test_private_build_commit_rejects_missing_or_malformed_token_manifest_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_commits: object,
) -> None:
    manifest_path = tmp_path / "prompt_token_budget_manifest_v1.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "prompt_token_budget_manifest_v1",
                "source_commits": source_commits,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        check_private_knot_boundary,
        "PROMPT_TOKEN_BUDGET_MANIFEST_PATH",
        manifest_path,
    )

    with pytest.raises(ValueError, match="source commits|private commit"):
        check_private_knot_boundary._private_prompt_build_commit()


def test_private_checkout_rejects_token_manifest_commit_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    tracked = private_root / "tracked.txt"
    tracked.write_text("committed\n", encoding="utf-8")
    _git(private_root, "init", "-q")
    _git(private_root, "config", "user.email", "test@example.com")
    _git(private_root, "config", "user.name", "Test")
    _git(private_root, "add", "tracked.txt")
    _git(private_root, "commit", "-qm", "fixture")
    manifest_path = tmp_path / "prompt_token_budget_manifest_v1.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "prompt_token_budget_manifest_v1",
                "source_commits": {"private": "f" * 40, "bundled": "b" * 40},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        check_private_knot_boundary,
        "PROMPT_TOKEN_BUDGET_MANIFEST_PATH",
        manifest_path,
    )

    with pytest.raises(ValueError, match="does not match public build-source pin"):
        check_private_knot_boundary._require_private_git_state(
            private_root,
            check_private_knot_boundary._private_prompt_build_commit(),
        )


def test_private_token_budget_rows_reject_stale_source_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root = tmp_path / "private"
    prompt_path = private_root / "prompts/mosaic/cohort_default/macro/china.zh.md"
    prompt_path.parent.mkdir(parents=True)
    prompt_content = b"private prompt fixture\n"
    prompt_path.write_bytes(prompt_content)
    manifest_path = tmp_path / "prompt_token_budget_manifest_v1.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "prompt_token_budget_manifest_v1",
                "rows": [
                    {
                        "source": "private",
                        "source_path": "cohort_default/macro/china.zh.md",
                        "source_sha256": check_private_knot_boundary._sha256_bytes(
                            prompt_content
                        ),
                        "source_bytes": len(prompt_content),
                    },
                    {
                        "source": "bundled",
                        "source_path": "cohort_default/macro/china.zh.md",
                        "source_sha256": "sha256:" + "a" * 64,
                        "source_bytes": 1,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        check_private_knot_boundary,
        "PROMPT_TOKEN_BUDGET_MANIFEST_PATH",
        manifest_path,
    )

    check_private_knot_boundary._check_private_token_budget_rows(private_root)
    prompt_path.write_text("stale private prompt fixture\n", encoding="utf-8")
    with pytest.raises(ValueError, match="private Prompt token budget row mismatch"):
        check_private_knot_boundary._check_private_token_budget_rows(private_root)


@pytest.mark.parametrize(
    ("source", "source_path", "expected_error"),
    [
        ("private", "../escaped.md", "path escapes prompt root"),
        (
            "private",
            "cohort_default/macro/missing.zh.md",
            "source is missing",
        ),
        ("bundled", "cohort_default/macro/china.zh.md", "rows are missing"),
    ],
)
def test_private_token_budget_rows_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    source_path: str,
    expected_error: str,
) -> None:
    private_root = tmp_path / "private"
    (private_root / "prompts/mosaic").mkdir(parents=True)
    manifest_path = tmp_path / "prompt_token_budget_manifest_v1.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "prompt_token_budget_manifest_v1",
                "rows": [
                    {
                        "source": source,
                        "source_path": source_path,
                        "source_sha256": "sha256:" + "a" * 64,
                        "source_bytes": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        check_private_knot_boundary,
        "PROMPT_TOKEN_BUDGET_MANIFEST_PATH",
        manifest_path,
    )

    with pytest.raises(ValueError, match=expected_error):
        check_private_knot_boundary._check_private_token_budget_rows(private_root)


def test_private_bootstrap_closes_private_prompt_and_state_trees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root = tmp_path / "private"
    parameter_path = private_root / "registry/knot/prompt_parameter_contract_v1.json"
    behavior_path = private_root / "registry/knot/prompt_behavior_contract_v1.json"
    parameter_path.parent.mkdir(parents=True)
    parameter_body = {"schema_version": "fixture", "parameters": []}
    parameter_hash = check_private_knot_boundary.canonical_hash(parameter_body)
    parameter_path.write_text(
        json.dumps({**parameter_body, "contract_hash": parameter_hash}),
        encoding="utf-8",
    )
    behavior = {"schema_version": "fixture", "agents": []}
    behavior_path.write_text(json.dumps(behavior), encoding="utf-8")
    prompt_root = private_root / "prompts/mosaic"
    state_root = private_root / "registry/prompt_parameter_states_v1"
    prompt_root.mkdir(parents=True)
    state_root.mkdir(parents=True)
    affected_prompt_refs = sorted(
        f"prompts/mosaic/cohort_default/sector/{agent}.{language}.md"
        for agent in (
            "agriculture",
            "biotech",
            "consumer",
            "energy",
            "financials",
            "industrials",
            "real_estate_construction",
            "relationship_mapper",
            "semiconductor",
            "technology",
        )
        for language in ("en", "zh")
    )
    for index in range(448):
        path = (
            private_root / affected_prompt_refs[index]
            if index < len(affected_prompt_refs)
            else prompt_root / f"prompt-{index:03}.md"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"prompt {index}\n", encoding="utf-8")
    for index in range(224):
        (state_root / f"state-{index:03}.json").write_text(
            json.dumps({"index": index}), encoding="utf-8"
        )

    def tree_hash(paths: list[Path]) -> str:
        return check_private_knot_boundary.canonical_hash(
            {
                "files": [
                    {
                        "ref": path.relative_to(private_root).as_posix(),
                        "content_hash": check_private_knot_boundary._sha256_bytes(
                            path.read_bytes()
                        ),
                    }
                    for path in paths
                ]
            }
        )

    bootstrap_body = {
        "schema_version": "private_prompt_parameter_bootstrap_release_v1",
        "parameter_contract_hash": parameter_hash,
        "behavior_contract_hash": check_private_knot_boundary.canonical_hash(behavior),
        "state_tree_hash": tree_hash(sorted(state_root.rglob("*.json"))),
        "prompt_tree_hash": tree_hash(sorted(prompt_root.rglob("*.md"))),
        "state_count": 224,
        "agent_count": 28,
        "cohort_count": 8,
        "prompt_count": 448,
    }
    bootstrap_path = private_root / check_private_knot_boundary.PRIVATE_PROMPT_BOOTSTRAP_PATH
    bootstrap_path.write_text(
        json.dumps(
            {
                **bootstrap_body,
                "release_hash": check_private_knot_boundary.canonical_hash(bootstrap_body),
            }
        ),
        encoding="utf-8",
    )

    check_private_knot_boundary._check_private_prompt_bootstrap(private_root)
    _git(private_root, "init", "-q")
    _git(private_root, "config", "user.email", "test@example.com")
    _git(private_root, "config", "user.name", "Test")
    _git(private_root, "add", ".")
    _git(private_root, "commit", "-qm", "baseline")
    baseline_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=private_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    for ref in affected_prompt_refs:
        path = private_root / ref
        path.write_text(path.read_text(encoding="utf-8") + "runtime rebase\n", encoding="utf-8")
    authority = {
        "schema_version": "agent_tool_contract_manifest_v1",
        "agent_count": 27,
        "execution_stage_count": 28,
        "tool_count": 31,
        "agents": [],
    }
    authority_path = tmp_path / "agent_tool_contract_manifest_v1.json"
    authority_path.write_text(json.dumps(authority), encoding="utf-8")
    public_commit = "a" * 40
    budget_path = tmp_path / "prompt_token_budget_manifest_v1.json"
    budget_path.write_text(
        json.dumps(
            {
                "schema_version": "prompt_token_budget_manifest_v1",
                "source_commits": {"private": "b" * 40, "bundled": public_commit},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        check_private_knot_boundary,
        "AGENT_TOOL_CONTRACT_MANIFEST_PATH",
        authority_path,
    )
    monkeypatch.setattr(
        check_private_knot_boundary,
        "PROMPT_TOKEN_BUDGET_MANIFEST_PATH",
        budget_path,
    )
    receipt = {
        "schema_version": "runtime_contract_rebase_receipt_v1",
        "previous_release_hash": check_private_knot_boundary.canonical_hash(
            bootstrap_body
        ),
        "baseline_commit": baseline_commit,
        "public_contract_commit": public_commit,
        "runtime_contract_authority_hash": check_private_knot_boundary.canonical_hash(
            authority
        ),
        "affected_prompt_refs": affected_prompt_refs,
        "rebase_tool_version": "runtime-contract-rebase-v1",
        "rebased_at": "2026-08-09T04:00:00Z",
    }
    rebased_body = {
        **bootstrap_body,
        "prompt_tree_hash": tree_hash(sorted(prompt_root.rglob("*.md"))),
        "rebase_receipt": receipt,
    }
    bootstrap_path.write_text(
        json.dumps(
            {
                **rebased_body,
                "release_hash": check_private_knot_boundary.canonical_hash(rebased_body),
            }
        ),
        encoding="utf-8",
    )
    check_private_knot_boundary._check_private_prompt_bootstrap(private_root)
    invalid_receipt = {**receipt, "runtime_contract_authority_hash": "sha256:" + "f" * 64}
    invalid_body = {**rebased_body, "rebase_receipt": invalid_receipt}
    bootstrap_path.write_text(
        json.dumps(
            {
                **invalid_body,
                "release_hash": check_private_knot_boundary.canonical_hash(invalid_body),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="runtime-contract authority hash mismatch"):
        check_private_knot_boundary._check_private_prompt_bootstrap(private_root)

    bootstrap_path.write_text(
        json.dumps(
            {
                **rebased_body,
                "release_hash": check_private_knot_boundary.canonical_hash(rebased_body),
            }
        ),
        encoding="utf-8",
    )
    bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    bootstrap["release_hash"] = "sha256:" + "f" * 64
    bootstrap_path.write_text(json.dumps(bootstrap), encoding="utf-8")
    with pytest.raises(ValueError, match="bootstrap release hash mismatch"):
        check_private_knot_boundary._check_private_prompt_bootstrap(private_root)
    bootstrap["release_hash"] = check_private_knot_boundary.canonical_hash(rebased_body)
    bootstrap_path.write_text(json.dumps(bootstrap), encoding="utf-8")
    (prompt_root / "prompt-020.md").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Prompt tree mismatch"):
        check_private_knot_boundary._check_private_prompt_bootstrap(private_root)


def test_private_boundary_fails_closed_without_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MOSAIC_PROMPTS_REPO", raising=False)
    monkeypatch.delenv("MOSAIC_PRIVATE_PROMPT_REPO", raising=False)

    with pytest.raises(ValueError, match="private Prompt repository is required"):
        check_private_knot_boundary.check(require_private=True)


def test_cross_repository_boundary_allows_deterministic_policy_id(
    tmp_path: Path,
) -> None:
    public_root, private_root, tracked = _content_boundary_fixture(tmp_path)
    tracked.write_text("risk.public_deterministic_policy\n", encoding="utf-8")

    check_private_knot_boundary._check_cross_repository_content_boundary(
        public_root, private_root
    )


def test_cross_repository_boundary_redacts_private_parameter_id(
    tmp_path: Path,
) -> None:
    public_root, private_root, tracked = _content_boundary_fixture(tmp_path)
    private_id = "china.private_prompt_signal"
    tracked.write_text(f"accidental {private_id}\n", encoding="utf-8")

    with pytest.raises(ValueError) as caught:
        check_private_knot_boundary._check_cross_repository_content_boundary(
            public_root, private_root
        )
    assert "parameter identifier" in str(caught.value)
    assert "tracked.txt" in str(caught.value)
    assert private_id not in str(caught.value)


def test_cross_repository_boundary_normalizes_and_redacts_private_calibration(
    tmp_path: Path,
) -> None:
    public_root, private_root, tracked = _content_boundary_fixture(tmp_path)
    private_text = "仅供私有候选使用的完整校准句子。"
    tracked.write_text("仅供私有候选使用的\n完整校准句子。\n", encoding="utf-8")

    with pytest.raises(ValueError) as caught:
        check_private_knot_boundary._check_cross_repository_content_boundary(
            public_root, private_root
        )
    assert "calibration text" in str(caught.value)
    assert "tracked.txt" in str(caught.value)
    assert private_text not in str(caught.value)


def test_cross_repository_boundary_rejects_private_calibration_clause(
    tmp_path: Path,
) -> None:
    public_root, private_root, tracked = _content_boundary_fixture(tmp_path)
    private_clause = "第二段私有校准内容不得对外公开"
    tracked.write_text("第二段私有校准内容\n不得对外公开\n", encoding="utf-8")

    with pytest.raises(ValueError) as caught:
        check_private_knot_boundary._check_cross_repository_content_boundary(
            public_root, private_root
        )
    assert "calibration text" in str(caught.value)
    assert "tracked.txt" in str(caught.value)
    assert private_clause not in str(caught.value)


def test_cross_repository_boundary_checks_staged_public_bytes(tmp_path: Path) -> None:
    public_root, private_root, tracked = _content_boundary_fixture(tmp_path)
    private_id = "china.private_prompt_signal"
    tracked.write_text(f"staged {private_id}\n", encoding="utf-8")
    _git(public_root, "add", "tracked.txt")
    tracked.write_text("ordinary public text\n", encoding="utf-8")

    with pytest.raises(ValueError) as caught:
        check_private_knot_boundary._check_cross_repository_content_boundary(
            public_root, private_root
        )
    assert "parameter identifier" in str(caught.value)
    assert "tracked.txt" in str(caught.value)
    assert private_id not in str(caught.value)


@pytest.mark.parametrize(
    ("private_text", "expected_error"),
    [
        ("china.private_prompt_signal", "parameter identifier"),
        ("仅供私有候选使用的\n完整校准句子。", "calibration text"),
    ],
)
def test_cross_repository_boundary_checks_untracked_public_text(
    tmp_path: Path,
    private_text: str,
    expected_error: str,
) -> None:
    public_root, private_root, _tracked = _content_boundary_fixture(tmp_path)
    untracked = public_root / "untracked.txt"
    untracked.write_text(f"accidental {private_text}\n", encoding="utf-8")

    with pytest.raises(ValueError) as caught:
        check_private_knot_boundary._check_cross_repository_content_boundary(
            public_root, private_root
        )
    assert expected_error in str(caught.value)
    assert "untracked.txt" in str(caught.value)
    assert private_text not in str(caught.value)


def test_private_content_scan_requires_clean_pinned_checkout(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    private_root.mkdir()
    tracked = private_root / "tracked.txt"
    tracked.write_text("committed\n", encoding="utf-8")
    _git(private_root, "init", "-q")
    _git(private_root, "config", "user.email", "test@example.com")
    _git(private_root, "config", "user.name", "Test")
    _git(private_root, "add", "tracked.txt")
    _git(private_root, "commit", "-qm", "fixture")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=private_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    check_private_knot_boundary._require_private_git_state(private_root, head)
    tracked.write_text("dirty\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be clean"):
        check_private_knot_boundary._require_private_git_state(private_root, head)
