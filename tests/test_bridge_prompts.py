"""Tests for prompts.* JSON-RPC handlers (Plan §11.5 4B).

Uses MOSAIC_REPO_ROOT to point the handler at a throwaway git repo, then
exercises read (working tree + ref), write (working tree + branch commit),
and the cohort_default fallback.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mosaic.bridge import handlers as _handlers_pkg  # noqa: F401
from mosaic.bridge.handlers import prompts as _prompts
from mosaic.bridge.protocol import RpcError
from mosaic.bridge.registry import get_handler
from mosaic.autoresearch.prompt_repo import init_private_prompt_repo
from mosaic.scorecard.store import ScorecardStore

DEFAULT_REL = "prompts/mosaic/cohort_default/macro/volatility.zh.md"
BRANCH = "cohort/crisis_2008/auto/volatility/2008-09-15"


def dispatch(method: str, params: dict):
    handler = get_handler(method)
    if handler is None:
        raise AssertionError(f"method '{method}' not registered")
    return handler(params)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout


def _valid_contract_prompt(agent: str, layer: str, fields: tuple[str, ...]) -> str:
    return f"""
# {agent}
## Role boundary
agent id {agent}; layer {layer}; downstream consumer daily-cycle; no portfolio decision outside role.
## Required inputs/tools
Required tools: get_rke_research_context and current data tools. If missing tool or tool unavailable, fallback to conservative output and confidence cap applies.
## RKE prior policy
get_rke_research_context is a redacted research prior, not current data, cannot replace current data, and cannot directly create trades. no trade without current data confirmation.
## Workflow
Collect evidence, handle contradiction, confirm current data, reason in role, emit structured JSON.
## Output schema
Exact fields: {", ".join(fields)}.
## Audit and footprint contract
Fields carry claim type, target, confidence, current-data confirmation, stale prior, contradictory prior, RKE context hash, ranking_policy_id, retrieval_rank, priority_bucket, truncation audit, truncated_item_count, current_data_confirmed, rke_context_hash.
## Privacy boundary
Never output report prose, source spans, source_span_ids, prompt body, local paths, URLs, reviewer text, or licensed metadata.
## Confidence policy
High confidence needs current data and two evidence families; fallback data caps confidence.
## Refusal and no-action behavior
If required data is unavailable, emit conservative no-action output inside schema.
## Autoresearch evolution contract
Mutable: thresholds and wording. Immutable: role boundary, output schema, required tools, current-data gate, rke-prior policy, privacy boundary, audit/footprint contract, shadow/promotion safety policy.
""".strip()


def _write_contract_prompt(
    private_repo: Path,
    *,
    agent: str = "volatility",
    layer: str = "macro",
    lang: str = "zh",
    text: str | None = None,
) -> None:
    fields = tuple(_prompts._AGENT_SCHEMA_FIELDS[agent])
    path = private_repo / "prompts" / "mosaic" / "cohort_default" / layer
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{agent}.{lang}.md").write_text(
        text or _valid_contract_prompt(agent, layer, fields),
        encoding="utf-8",
    )


def _init_private_prompt_repo_for_test(private_repo: Path, project_root: Path) -> None:
    init_private_prompt_repo(private_repo, project_root=project_root)
    _git(private_repo, "config", "user.name", "Test")
    _git(private_repo, "config", "user.email", "test@example.com")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    seed = repo / "prompts" / "mosaic" / "cohort_default" / "macro"
    seed.mkdir(parents=True)
    (seed / "volatility.zh.md").write_text("base zh\n## 输出 schema\n", encoding="utf-8")
    (seed / "volatility.en.md").write_text("base en\n## Output schema\n", encoding="utf-8")
    super_seed = repo / "prompts" / "mosaic" / "cohort_default" / "superinvestor"
    super_seed.mkdir(parents=True)
    for agent in ("druckenmiller", "munger", "burry", "ackman"):
        (super_seed / f"{agent}.zh.md").write_text(
            f"{agent} zh\n## 输出 schema\n", encoding="utf-8"
        )
        (super_seed / f"{agent}.en.md").write_text(
            f"{agent} en\n## Output schema\n", encoding="utf-8"
        )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed")
    (repo / "data").mkdir()
    (repo / ".gitignore").write_text("data/\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", "gitignore")
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(repo))
    return repo


# ── prompts.read ──────────────────────────────────────────────────────────


class TestRead:
    def test_working_tree(self, repo: Path):
        r = dispatch("prompts.read", {"agent": "volatility", "cohort": "cohort_default", "lang": "zh"})
        assert r["content"].startswith("base zh")
        assert r["path"] == DEFAULT_REL

    def test_cohort_default_fallback(self, repo: Path):
        # crisis_2008 has no file → falls back to cohort_default.
        r = dispatch("prompts.read", {"agent": "volatility", "cohort": "crisis_2008", "lang": "en"})
        assert r["content"].startswith("base en")
        assert "cohort_default" in r["path"]

    def test_at_ref(self, repo: Path):
        r = dispatch("prompts.read", {"agent": "volatility", "cohort": "cohort_default", "lang": "zh", "ref": "main"})
        assert r["content"].startswith("base zh")

    def test_unknown_agent(self, repo: Path):
        with pytest.raises(RpcError, match="unknown agent"):
            dispatch("prompts.read", {"agent": "nope", "cohort": "cohort_default", "lang": "zh"})

    def test_superinvestor_roster_uses_canonical_four(self, repo: Path):
        for agent in ("druckenmiller", "munger", "burry", "ackman"):
            r = dispatch(
                "prompts.read",
                {"agent": agent, "cohort": "cohort_default", "lang": "zh"},
            )
            assert r["content"].startswith(f"{agent} zh")
            assert r["path"] == f"prompts/mosaic/cohort_default/superinvestor/{agent}.zh.md"

        for removed_agent in ("aschenbrenner", "baker"):
            with pytest.raises(RpcError, match="unknown agent"):
                dispatch(
                    "prompts.read",
                    {"agent": removed_agent, "cohort": "cohort_default", "lang": "zh"},
                )

    def test_bad_lang(self, repo: Path):
        with pytest.raises(RpcError, match="lang"):
            dispatch("prompts.read", {"agent": "volatility", "cohort": "cohort_default", "lang": "fr"})

    def test_missing_file(self, repo: Path):
        with pytest.raises(RpcError, match="not found"):
            dispatch("prompts.read", {"agent": "cio", "cohort": "cohort_default", "lang": "zh"})


# ── prompts.write ─────────────────────────────────────────────────────────


class TestWrite:
    def test_default_branch_routes_to_project_git(self, repo: Path):
        # Orchestrator path: branch + no target → project feature-branch commit;
        # no escape hatch / private repo required (keeps the autoresearch loop
        # working until Phase 5 moves eval/read to the private repo).
        r = dispatch("prompts.write", {
            "agent": "volatility", "cohort": "crisis_2008",
            "contents": {"zh": "new zh\n## 输出 schema\n"},
            "branch": BRANCH,
        })
        assert r["target"] == "project_git"
        assert len(r["commit_hash"]) == 40
        assert not (repo / "prompts/mosaic/crisis_2008").exists()

    def test_private_git_requires_config(self, repo: Path):
        with pytest.raises(RpcError, match="MOSAIC_PROMPTS_REPO"):
            dispatch("prompts.write", {
                "agent": "volatility", "cohort": "crisis_2008",
                "contents": {"zh": "new zh\n"},
                "target": "private_git",
                "branch": BRANCH,
            })

    def test_to_private_git_branch_commits(self, repo: Path, tmp_path: Path, monkeypatch):
        private_repo = tmp_path / "private-prompts"
        init_private_prompt_repo(private_repo, project_root=repo)
        monkeypatch.setenv("MOSAIC_PRIVATE_PROMPT_REPO", str(private_repo))

        r = dispatch("prompts.write", {
            "agent": "volatility", "cohort": "crisis_2008",
            "contents": {"zh": "new zh\n## 输出 schema\n", "en": "new en\n## Output schema\n"},
            "target": "private_git",
            "branch": BRANCH,
        })
        assert r["target"] == "private_git"
        assert r["prompt_repo_id"] == "private"
        assert len(r["prompt_base_commit_hash"]) == 40
        assert len(r["prompt_commit_hash"]) == 40
        assert len(r["prompt_sha256"]) == 64
        assert r["branch"] == BRANCH
        assert len(r["paths"]) == 2
        assert not (repo / "prompts/mosaic/crisis_2008").exists()
        assert not (private_repo / "prompts/mosaic/crisis_2008").exists()
        prompt_at_branch = _git(
            private_repo,
            "show",
            f"{BRANCH}:prompts/mosaic/crisis_2008/macro/volatility.zh.md",
        )
        assert prompt_at_branch.startswith("new zh")

    def test_to_private_git_accepts_mosaic_prompts_repo(self, repo: Path, tmp_path: Path, monkeypatch):
        private_repo = tmp_path / "MOSAIC-Prompts"
        init_private_prompt_repo(private_repo, project_root=repo)
        monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
        monkeypatch.setenv("MOSAIC_PROMPTS_REPO_ID", "haphap/MOSAIC-Prompts")

        r = dispatch("prompts.write", {
            "agent": "volatility", "cohort": "crisis_2008",
            "contents": {"zh": "new zh\n"},
            "target": "private_git",
            "branch": BRANCH,
        })

        assert r["target"] == "private_git"
        assert r["prompt_repo_id"] == "haphap/MOSAIC-Prompts"
        assert len(r["prompt_commit_hash"]) == 40

    def test_to_project_git_branch_commits(self, repo: Path):
        r = dispatch("prompts.write", {
            "agent": "volatility", "cohort": "crisis_2008",
            "contents": {"zh": "new zh\n## 输出 schema\n", "en": "new en\n## Output schema\n"},
            "target": "project_git",
            "branch": BRANCH,
        })
        assert r["target"] == "project_git"
        assert r["prompt_repo_id"] == "project"
        assert len(r["commit_hash"]) == 40
        assert len(r["prompt_sha256"]) == 64
        assert r["branch"] == BRANCH
        assert len(r["paths"]) == 2
        # primary tree untouched (commit built in a worktree)
        assert not (repo / "prompts/mosaic/crisis_2008").exists()
        # readable back at the branch ref
        back = dispatch("prompts.read", {
            "agent": "volatility", "cohort": "crisis_2008", "lang": "zh", "ref": BRANCH,
        })
        assert back["content"].startswith("new zh")

    def test_to_working_tree(self, repo: Path):
        r = dispatch("prompts.write", {
            "agent": "volatility", "cohort": "crisis_2008",
            "contents": {"zh": "wt zh\n"},
            "allow_public_prompt_write": True,
        })
        assert "commit_hash" not in r
        assert r["target"] == "working_tree"
        assert len(r["prompt_sha256"]) == 64
        assert (repo / "prompts/mosaic/crisis_2008/macro/volatility.zh.md").exists()

    def test_working_tree_requires_allow(self, repo: Path):
        with pytest.raises(RpcError, match="allow_public_prompt_write"):
            dispatch("prompts.write", {
                "agent": "volatility", "cohort": "crisis_2008",
                "contents": {"zh": "wt zh\n"},
            })

    def test_bad_contents(self, repo: Path):
        with pytest.raises(RpcError, match="contents"):
            dispatch("prompts.write", {"agent": "volatility", "cohort": "c", "contents": {}})

    def test_bad_lang_key(self, repo: Path):
        with pytest.raises(RpcError, match="contents"):
            dispatch("prompts.write", {"agent": "volatility", "cohort": "c", "contents": {"fr": "x"}})


def test_prompts_methods_registered():
    from mosaic.bridge.registry import all_methods

    assert {
        "prompts.read",
        "prompts.write",
        "prompts.init_private_repo",
        "prompts.audit_versions",
        "prompts.preflight",
        "prompts.contract_check",
        "prompts.verify_release",
    }.issubset(set(all_methods()))


def test_init_private_repo_rpc(repo: Path, tmp_path: Path):
    private_repo = tmp_path / "private-prompts"
    r = dispatch("prompts.init_private_repo", {"path": str(private_repo)})

    assert r["seeded"] is False
    assert len(r["commit_hash"]) == 40
    assert (private_repo / "prompts" / "mosaic" / ".gitkeep").exists()


def test_init_private_repo_rpc_can_seed_baseline(repo: Path, tmp_path: Path):
    private_repo = tmp_path / "private-prompts"
    r = dispatch("prompts.init_private_repo", {"path": str(private_repo), "seed_baseline": True})

    assert r["seeded"] is True
    assert (
        private_repo
        / "prompts"
        / "mosaic"
        / "cohort_default"
        / "macro"
        / "volatility.zh.md"
    ).read_text(encoding="utf-8").startswith("base zh")


def test_audit_versions_returns_metadata_only(repo: Path, tmp_path: Path, monkeypatch):
    store = ScorecardStore(tmp_path / "scorecard.db")
    monkeypatch.setattr(_prompts, "_store", lambda: store)
    vid = store.create_prompt_version(
        cohort="cohort_default",
        agent="volatility",
        branch_name=BRANCH,
        base_commit_hash="a" * 40,
    )
    store.set_version_mutation(
        vid,
        "b" * 40,
        "summary only",
        prompt_repo_id="private",
        prompt_sha256="f" * 64,
        code_commit_hash="c" * 40,
    )

    result = dispatch("prompts.audit_versions", {"limit": 5})

    assert result["versions"][0]["id"] == vid
    assert "content" not in result["versions"][0]
    assert "zh_prompt" not in result["versions"][0]


def test_preflight_blocks_without_private_prompt_source(repo: Path):
    result = dispatch(
        "prompts.preflight",
        {"agents": ["volatility"], "langs": ["zh"]},
    )

    assert result["ready"] is False
    assert result["blocked_count"] == 1
    assert result["source_status"] == {
        "ready": False,
        "blocked_reason": "private_prompt_unavailable",
        "resolved_source": "",
        "prompt_repo_id": "",
        "prompt_repo_revision": "",
        "prompt_repo_dirty_count": 0,
    }
    row = result["rows"][0]
    assert row["status"] == "blocked"
    assert row["blocked_reason"] == "private_prompt_unavailable"
    assert row["fallback_used"] is False
    assert "content" not in row


def test_preflight_records_private_prompt_provenance(repo: Path, tmp_path: Path, monkeypatch):
    private_repo = tmp_path / "MOSAIC-Prompts"
    init_private_prompt_repo(private_repo, project_root=repo, seed_baseline=True)
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    result = dispatch(
        "prompts.preflight",
        {"agents": ["volatility"], "langs": ["zh", "en"]},
    )

    assert result["ready"] is True
    assert result["blocked_count"] == 0
    assert result["row_count"] == 2
    assert result["source_status"]["ready"] is True
    assert result["source_status"]["resolved_source"] == "private_repo"
    assert result["source_status"]["prompt_repo_dirty_count"] == 0
    for row in result["rows"]:
        assert row["status"] == "ready"
        assert row["prompt_repo_id"] == "https://github.com/haphap/MOSAIC-Prompts"
        assert len(row["prompt_repo_revision"]) == 40
        assert row["prompt_file_path"].startswith("prompts/mosaic/cohort_default/")
        assert len(row["prompt_sha256"]) == 64
        assert row["resolved_source"] == "private_repo"
        assert row["fallback_used"] is False
        assert "content" not in row


def test_preflight_blocks_dirty_private_prompt_repo(
    repo: Path, tmp_path: Path, monkeypatch
):
    private_repo = tmp_path / "MOSAIC-Prompts"
    init_private_prompt_repo(private_repo, project_root=repo, seed_baseline=True)
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
    prompt_file = (
        private_repo
        / "prompts"
        / "mosaic"
        / "cohort_default"
        / "macro"
        / "volatility.zh.md"
    )
    prompt_file.write_text("dirty zh\n## 输出 schema\n", encoding="utf-8")

    result = dispatch(
        "prompts.preflight",
        {"agents": ["volatility"], "langs": ["zh"]},
    )

    assert result["ready"] is False
    assert result["source_status"]["blocked_reason"] == "private_prompt_repo_dirty"
    assert result["source_status"]["resolved_source"] == "private_repo"
    assert (
        result["source_status"]["prompt_repo_id"]
        == "https://github.com/haphap/MOSAIC-Prompts"
    )
    assert len(result["source_status"]["prompt_repo_revision"]) == 40
    assert result["source_status"]["prompt_repo_dirty_count"] == 1
    assert result["rows"][0]["blocked_reason"] == "private_prompt_repo_dirty"
    assert result["rows"][0]["fallback_used"] is False
    assert "content" not in result["rows"][0]


def test_preflight_allows_git_backed_prompts_root(repo: Path, tmp_path: Path, monkeypatch):
    private_repo = tmp_path / "MOSAIC-Prompts"
    init_private_prompt_repo(private_repo, project_root=repo, seed_baseline=True)
    monkeypatch.setenv("MOSAIC_PROMPTS_ROOT", str(private_repo / "prompts" / "mosaic"))

    result = dispatch(
        "prompts.preflight",
        {"agents": ["volatility"], "langs": ["zh"]},
    )

    assert result["ready"] is True
    assert result["source_status"]["resolved_source"] == "private_root"
    assert result["source_status"]["prompt_repo_dirty_count"] == 0
    row = result["rows"][0]
    assert row["resolved_source"] == "private_root"
    assert row["prompt_file_path"] == "prompts/mosaic/cohort_default/macro/volatility.zh.md"


def test_preflight_blocks_dirty_prompts_root(repo: Path, tmp_path: Path, monkeypatch):
    private_repo = tmp_path / "MOSAIC-Prompts"
    init_private_prompt_repo(private_repo, project_root=repo, seed_baseline=True)
    monkeypatch.setenv("MOSAIC_PROMPTS_ROOT", str(private_repo / "prompts" / "mosaic"))
    prompt_file = (
        private_repo
        / "prompts"
        / "mosaic"
        / "cohort_default"
        / "macro"
        / "volatility.zh.md"
    )
    prompt_file.write_text("dirty zh\n## 输出 schema\n", encoding="utf-8")

    result = dispatch(
        "prompts.preflight",
        {"agents": ["volatility"], "langs": ["zh"]},
    )

    assert result["ready"] is False
    assert result["source_status"]["blocked_reason"] == "private_prompt_repo_dirty"
    assert result["source_status"]["resolved_source"] == "private_root"
    assert (
        result["source_status"]["prompt_repo_id"]
        == "https://github.com/haphap/MOSAIC-Prompts"
    )
    assert len(result["source_status"]["prompt_repo_revision"]) == 40
    assert result["source_status"]["prompt_repo_dirty_count"] == 1
    assert result["rows"][0]["blocked_reason"] == "private_prompt_repo_dirty"


def test_preflight_rejects_project_prompt_root(repo: Path, monkeypatch):
    monkeypatch.setenv("MOSAIC_PROMPTS_ROOT", str(repo / "prompts" / "mosaic"))

    result = dispatch(
        "prompts.preflight",
        {"agents": ["volatility"], "langs": ["zh"]},
    )

    assert result["ready"] is False
    assert result["source_status"]["blocked_reason"] == "prompt_provenance_unavailable"
    assert result["rows"][0]["blocked_reason"] == "prompt_provenance_unavailable"


def test_verify_release_checks_pin_metadata(repo: Path, tmp_path: Path, monkeypatch):
    store = ScorecardStore(tmp_path / "scorecard.db")
    monkeypatch.setattr(_prompts, "_store", lambda: store)
    private_repo = tmp_path / "private-prompts"
    init_private_prompt_repo(private_repo, project_root=repo)
    monkeypatch.setenv("MOSAIC_PRIVATE_PROMPT_REPO", str(private_repo))
    write = dispatch("prompts.write", {
        "agent": "volatility",
        "cohort": "cohort_default",
        "contents": {
            "zh": "release zh\n## 输出 schema\n",
            "en": "release en\n## Output schema\n",
        },
        "target": "private_git",
        "branch": BRANCH,
    })
    vid = store.create_prompt_version(
        cohort="cohort_default",
        agent="volatility",
        branch_name=BRANCH,
        base_commit_hash="a" * 40,
        code_commit_hash="c" * 40,
    )
    store.set_version_mutation(
        vid,
        write["prompt_commit_hash"],
        "release candidate",
        prompt_repo_id="private",
        prompt_base_commit_hash=write["prompt_base_commit_hash"],
        prompt_sha256=write["prompt_sha256"],
        code_commit_hash="c" * 40,
    )
    store.decide_version(vid, "keep")

    result = dispatch("prompts.verify_release", {"version_id": vid})

    assert result["ready"] is True
    assert result["checks"]["sha_ok"] is True
    assert result["checks"]["compatible"] is True
    assert result["pin"]["prompt_commit_hash"] == write["prompt_commit_hash"]
    assert "content" not in result


def test_contract_check_accepts_valid_private_prompts_by_layer(
    repo: Path, tmp_path: Path, monkeypatch
):
    private_repo = tmp_path / "MOSAIC-Prompts"
    _init_private_prompt_repo_for_test(private_repo, repo)
    agents = {
        "volatility": "macro",
        "semiconductor": "sector",
        "munger": "superinvestor",
        "cro": "decision",
    }
    for agent, layer in agents.items():
        for lang in ("zh", "en"):
            _write_contract_prompt(private_repo, agent=agent, layer=layer, lang=lang)
    _git(private_repo, "add", "prompts/mosaic")
    _git(private_repo, "commit", "-m", "contract prompts")
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    result = dispatch(
        "prompts.contract_check",
        {"agents": list(agents), "langs": ["zh", "en"], "benchmark_run_id": "bench-contract"},
    )

    assert result["ready"] is True
    assert result["row_count"] == 8
    assert result["counts_by_layer"] == {
        "macro": 2,
        "sector": 2,
        "superinvestor": 2,
        "decision": 2,
    }
    assert all(row["prompt_contract_check_ref"].startswith("prompt-contract:") for row in result["rows"])
    assert "Role boundary" not in str(result)
    assert "content" not in result["rows"][0]


def test_formal_release_checks_emit_no_body_rows(repo: Path, tmp_path: Path, monkeypatch):
    private_repo = tmp_path / "MOSAIC-Prompts"
    _init_private_prompt_repo_for_test(private_repo, repo)
    agents = {
        "volatility": "macro",
        "semiconductor": "sector",
        "munger": "superinvestor",
        "cro": "decision",
    }
    for agent, layer in agents.items():
        for lang in ("zh", "en"):
            _write_contract_prompt(private_repo, agent=agent, layer=layer, lang=lang)
    _git(private_repo, "add", "prompts/mosaic")
    _git(private_repo, "commit", "-m", "contract prompts")
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    result = dispatch(
        "prompts.formal_release_checks",
        {
            "agents": list(agents),
            "langs": ["zh", "en"],
            "benchmark_run_id": "bench-release",
        },
    )

    assert result["ready"] is True
    assert result["row_count"] == 8
    assert result["ready_count"] == 8
    assert result["blocked_reasons"] == []
    assert all(row["prompt_version_id"] > 0 for row in result["rows"])
    assert all(row["verify_release_passed"] is True for row in result["rows"])
    assert all(row["leak_drift_passed"] is True for row in result["rows"])
    assert all(row["prompt_contract_check_passed"] is True for row in result["rows"])
    assert "Role boundary" not in str(result)
    assert "content" not in result["rows"][0]


def test_formal_release_checks_block_invalid_contract(
    repo: Path, tmp_path: Path, monkeypatch
):
    private_repo = tmp_path / "MOSAIC-Prompts"
    _init_private_prompt_repo_for_test(private_repo, repo)
    _write_contract_prompt(private_repo, text="missing contract sections")
    _git(private_repo, "add", "prompts/mosaic")
    _git(private_repo, "commit", "-m", "bad prompt")
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    result = dispatch(
        "prompts.formal_release_checks",
        {"agents": ["volatility"], "langs": ["zh"], "benchmark_run_id": "bench-release"},
    )

    assert result["ready"] is False
    assert result["row_count"] == 1
    assert result["blocked_count"] == 1
    assert "prompt_contract_check_not_passed" in result["blocked_reasons"]
    assert result["rows"][0]["verify_release_passed"] is False
    assert result["rows"][0]["leak_drift_passed"] is False


def test_contract_check_blocks_missing_section(repo: Path, tmp_path: Path, monkeypatch):
    private_repo = tmp_path / "MOSAIC-Prompts"
    _init_private_prompt_repo_for_test(private_repo, repo)
    text = _valid_contract_prompt(
        "volatility", "macro", tuple(_prompts._AGENT_SCHEMA_FIELDS["volatility"])
    ).replace("## Privacy boundary", "## Privacy rules")
    _write_contract_prompt(private_repo, text=text)
    _git(private_repo, "add", "prompts/mosaic")
    _git(private_repo, "commit", "-m", "bad contract prompt")
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    result = dispatch("prompts.contract_check", {"agents": ["volatility"], "langs": ["zh"]})

    assert result["ready"] is False
    assert "required_section_missing:privacy_boundary" in result["blocked_reasons"]


def test_contract_check_blocks_missing_schema_field(repo: Path, tmp_path: Path, monkeypatch):
    private_repo = tmp_path / "MOSAIC-Prompts"
    _init_private_prompt_repo_for_test(private_repo, repo)
    fields = tuple(f for f in _prompts._AGENT_SCHEMA_FIELDS["volatility"] if f != "vix_regime")
    _write_contract_prompt(
        private_repo,
        text=_valid_contract_prompt("volatility", "macro", fields),
    )
    _git(private_repo, "add", "prompts/mosaic")
    _git(private_repo, "commit", "-m", "schema drift prompt")
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    result = dispatch("prompts.contract_check", {"agents": ["volatility"], "langs": ["zh"]})

    assert result["ready"] is False
    assert "schema_field_missing:vix_regime" in result["blocked_reasons"]


def test_contract_check_blocks_rke_prior_as_current_data(
    repo: Path, tmp_path: Path, monkeypatch
):
    private_repo = tmp_path / "MOSAIC-Prompts"
    _init_private_prompt_repo_for_test(private_repo, repo)
    text = _valid_contract_prompt(
        "volatility", "macro", tuple(_prompts._AGENT_SCHEMA_FIELDS["volatility"])
    ) + "\nRKE prior is current data."
    _write_contract_prompt(private_repo, text=text)
    _git(private_repo, "add", "prompts/mosaic")
    _git(private_repo, "commit", "-m", "unsafe rke prompt")
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    result = dispatch("prompts.contract_check", {"agents": ["volatility"], "langs": ["zh"]})

    assert result["ready"] is False
    assert "rke_prior_treated_as_current_data" in result["blocked_reasons"]


def test_contract_check_blocks_cross_run_prompt_row(
    repo: Path, tmp_path: Path, monkeypatch
):
    private_repo = tmp_path / "MOSAIC-Prompts"
    _init_private_prompt_repo_for_test(private_repo, repo)
    _write_contract_prompt(private_repo)
    _git(private_repo, "add", "prompts/mosaic")
    _git(private_repo, "commit", "-m", "contract prompt")
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
    preflight = dispatch("prompts.preflight", {"agents": ["volatility"], "langs": ["zh"]})
    row = {**preflight["rows"][0], "benchmark_run_id": "other-run"}

    result = dispatch(
        "prompts.contract_check",
        {"benchmark_run_id": "bench-run", "prompt_rows": [row]},
    )

    assert result["ready"] is False
    assert "benchmark_run_id_mismatch" in result["blocked_reasons"]


def test_contract_check_blocks_bilingual_category_drift(
    repo: Path, tmp_path: Path, monkeypatch
):
    private_repo = tmp_path / "MOSAIC-Prompts"
    _init_private_prompt_repo_for_test(private_repo, repo)
    good = _valid_contract_prompt(
        "volatility", "macro", tuple(_prompts._AGENT_SCHEMA_FIELDS["volatility"])
    )
    _write_contract_prompt(private_repo, lang="zh", text=good)
    _write_contract_prompt(private_repo, lang="en", text=good.replace("## Workflow", "## Steps"))
    _git(private_repo, "add", "prompts/mosaic")
    _git(private_repo, "commit", "-m", "bilingual drift prompt")
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    result = dispatch(
        "prompts.contract_check",
        {"agents": ["volatility"], "langs": ["zh", "en"]},
    )

    assert result["ready"] is False
    assert "bilingual_contract_category_drift" in result["blocked_reasons"]
