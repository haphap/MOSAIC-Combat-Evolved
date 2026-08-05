"""Tests for prompts.* JSON-RPC handlers (Plan §11.5 4B).

Uses MOSAIC_REPO_ROOT to point the handler at a throwaway git repo, then
exercises read-only history and prompt-contract inspection.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from mosaic.bridge import handlers as _handlers_pkg  # noqa: F401
from mosaic.bridge.handlers import prompts as _prompts
from mosaic.bridge.protocol import RpcError
from mosaic.bridge.registry import get_handler
from mosaic.autoresearch.prompt_repo import init_private_prompt_repo

DEFAULT_REL = "prompts/mosaic/cohort_default/macro/us_financial_conditions.zh.md"
BRANCH = "cohort/crisis_2008/auto/us_financial_conditions/2008-09-15"
_MACRO_SCHEMA_FIELDS = _prompts._AGENT_SCHEMA_FIELDS["us_financial_conditions"]


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
    tools = _prompts._RUNTIME_PROMPT_CONTRACTS[agent]["required_tools"]
    return f"""
# {agent} {layer} role
Goal: stay inside the {agent} role and use only the frozen PIT/as-of evidence.
<!-- cohort-behavior:start -->
Assume no regime beyond the supplied evidence.
<!-- cohort-behavior:end -->
Tool: call only {", ".join(tools)}; reject insufficient evidence.
The runtime structured schema is authoritative.
<!-- runtime-evidence-contract:start -->
## Runtime Evidence Output Contract
Output fields include: {", ".join(fields)}.
Required runtime tools: {", ".join(tools)}.
Emit claims and claim_refs. Claims cite evidence_id values through evidence_ids;
INTERPRETATION claims cite research_rule_refs. Reject or abstain when evidence is insufficient.
<!-- runtime-evidence-contract:end -->
""".strip()


def _valid_zh_contract_prompt(agent: str, layer: str, fields: tuple[str, ...]) -> str:
    tools = _prompts._RUNTIME_PROMPT_CONTRACTS[agent]["required_tools"]
    return f"""
# {agent} {layer} 角色
目标：仅在 {agent} 角色内使用冻结的截至时点/PIT 证据。
<!-- cohort-behavior:start -->
除已提供证据外不假设市场状态。
<!-- cohort-behavior:end -->
工具：只能调用 {", ".join(tools)}；证据不足时拒绝输出。
运行时结构化 schema 是唯一权威。
<!-- runtime-evidence-contract:start -->
## Runtime Evidence Output Contract
输出字段包括：{", ".join(fields)}。
Required runtime tools: {", ".join(tools)}。
输出 claims 和 claim_refs。claims 通过 evidence_ids 引用 evidence_id；
INTERPRETATION claims 引用 research_rule_refs。证据不足时拒绝或弃权。
<!-- runtime-evidence-contract:end -->
""".strip()


def _write_contract_prompt(
    private_repo: Path,
    *,
    agent: str = "us_financial_conditions",
    layer: str = "macro",
    lang: str = "zh",
    text: str | None = None,
) -> None:
    fields = (
        _MACRO_SCHEMA_FIELDS
        if layer == "macro"
        else tuple(_prompts._AGENT_SCHEMA_FIELDS[agent])
    )
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
    (seed / "us_financial_conditions.zh.md").write_text(
        "base zh\n## 输出 schema\n", encoding="utf-8"
    )
    (seed / "us_financial_conditions.en.md").write_text(
        "base en\n## Output schema\n", encoding="utf-8"
    )
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
        r = dispatch("prompts.read", {"agent": "us_financial_conditions", "cohort": "cohort_default", "lang": "zh"})
        assert r["content"].startswith("base zh")
        assert r["path"] == DEFAULT_REL

    def test_cohort_default_fallback(self, repo: Path):
        # crisis_2008 has no file → falls back to cohort_default.
        r = dispatch("prompts.read", {"agent": "us_financial_conditions", "cohort": "crisis_2008", "lang": "en"})
        assert r["content"].startswith("base en")
        assert "cohort_default" in r["path"]

    def test_at_ref(self, repo: Path):
        r = dispatch("prompts.read", {"agent": "us_financial_conditions", "cohort": "cohort_default", "lang": "zh", "ref": "main"})
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
            dispatch("prompts.read", {"agent": "us_financial_conditions", "cohort": "cohort_default", "lang": "fr"})

    def test_missing_file(self, repo: Path):
        with pytest.raises(RpcError, match="not found"):
            dispatch("prompts.read", {"agent": "cio", "cohort": "cohort_default", "lang": "zh"})


def test_retired_prompt_writer_methods_are_absent():
    from mosaic.bridge.registry import all_methods

    methods = set(all_methods())
    assert {
        "prompts.write",
        "prompts.candidate_state",
        "prompts.abort_candidate",
        "prompts.verify_release",
    }.isdisjoint(methods)
    assert {
        "prompts.read",
        "prompts.init_private_repo",
        "prompts.audit_versions",
        "prompts.preflight",
        "prompts.contract_check",
        "prompts.formal_release_checks",
    }.issubset(methods)


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
        / "us_financial_conditions.zh.md"
    ).read_text(encoding="utf-8").startswith("base zh")


def test_audit_versions_returns_metadata_only(repo: Path, monkeypatch):
    row = {
        "id": 1,
        "cohort": "cohort_default",
        "agent": "us_financial_conditions",
        "status": "keep",
        "branch_name": BRANCH,
        "base_commit_hash": "a" * 40,
        "modification_commit_hash": "b" * 40,
        "prompt_repo_id": "private",
        "prompt_sha256": "f" * 64,
        "code_commit_hash": "c" * 40,
        "modification_summary": "summary only",
    }

    class AuditStore:
        def list_prompt_versions(self, **_filters):
            return [row]

    monkeypatch.setattr(_prompts, "_store", AuditStore)
    result = dispatch("prompts.audit_versions", {"limit": 5})

    assert result["versions"][0]["id"] == 1
    assert "content" not in result["versions"][0]
    assert "zh_prompt" not in result["versions"][0]


def test_preflight_blocks_without_private_prompt_source(repo: Path):
    result = dispatch(
        "prompts.preflight",
        {"agents": ["us_financial_conditions"], "langs": ["zh"]},
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
        {"agents": ["us_financial_conditions"], "langs": ["zh", "en"]},
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


def test_preflight_hashes_raw_prompt_at_the_requested_release_commit(
    repo: Path, tmp_path: Path, monkeypatch
):
    private_repo = tmp_path / "MOSAIC-Prompts"
    init_private_prompt_repo(private_repo, project_root=repo, seed_baseline=True)
    _git(private_repo, "config", "user.name", "Test")
    _git(private_repo, "config", "user.email", "test@example.com")
    first_commit = _git(private_repo, "rev-parse", "HEAD").strip()
    relative_path = (
        "prompts/mosaic/cohort_default/macro/us_financial_conditions.zh.md"
    )
    first_text = _git(private_repo, "show", f"{first_commit}:{relative_path}")
    (private_repo / relative_path).write_text("new head prompt\n", encoding="utf-8")
    _git(private_repo, "add", relative_path)
    _git(private_repo, "commit", "-m", "advance prompt head")
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    with pytest.raises(RpcError, match="verified release context"):
        dispatch(
            "prompts.preflight",
            {
                "agents": ["us_financial_conditions"],
                "langs": ["zh"],
                "prompt_repo_revision": first_commit,
            },
        )

    result = dispatch(
        "prompts.preflight",
        {
            "agents": ["us_financial_conditions"],
            "langs": ["zh"],
            "prompt_repo_revision": first_commit,
            "allow_non_head_revision": True,
        },
    )

    assert result["ready"] is True
    assert result["source_status"]["prompt_repo_revision"] == first_commit
    assert result["rows"][0]["prompt_sha256"] == hashlib.sha256(
        first_text.encode("utf-8")
    ).hexdigest()


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
        / "us_financial_conditions.zh.md"
    )
    prompt_file.write_text("dirty zh\n## 输出 schema\n", encoding="utf-8")

    result = dispatch(
        "prompts.preflight",
        {"agents": ["us_financial_conditions"], "langs": ["zh"]},
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
        {"agents": ["us_financial_conditions"], "langs": ["zh"]},
    )

    assert result["ready"] is True
    assert result["source_status"]["resolved_source"] == "private_root"
    assert result["source_status"]["prompt_repo_dirty_count"] == 0
    row = result["rows"][0]
    assert row["resolved_source"] == "private_root"
    assert row["prompt_file_path"] == (
        "prompts/mosaic/cohort_default/macro/us_financial_conditions.zh.md"
    )


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
        / "us_financial_conditions.zh.md"
    )
    prompt_file.write_text("dirty zh\n## 输出 schema\n", encoding="utf-8")

    result = dispatch(
        "prompts.preflight",
        {"agents": ["us_financial_conditions"], "langs": ["zh"]},
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
        {"agents": ["us_financial_conditions"], "langs": ["zh"]},
    )

    assert result["ready"] is False
    assert result["source_status"]["blocked_reason"] == "prompt_provenance_unavailable"
    assert result["rows"][0]["blocked_reason"] == "prompt_provenance_unavailable"



def test_contract_check_accepts_valid_private_prompts_by_layer(
    repo: Path, tmp_path: Path, monkeypatch
):
    private_repo = tmp_path / "MOSAIC-Prompts"
    _init_private_prompt_repo_for_test(private_repo, repo)
    agents = {
        "us_financial_conditions": "macro",
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


def test_contract_check_accepts_localized_zh_contract(repo: Path, tmp_path: Path, monkeypatch):
    private_repo = tmp_path / "MOSAIC-Prompts"
    _init_private_prompt_repo_for_test(private_repo, repo)
    fields = _MACRO_SCHEMA_FIELDS
    _write_contract_prompt(
        private_repo,
        text=_valid_zh_contract_prompt("us_financial_conditions", "macro", fields),
    )
    _git(private_repo, "add", "prompts/mosaic")
    _git(private_repo, "commit", "-m", "localized zh contract prompt")
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    result = dispatch("prompts.contract_check", {"agents": ["us_financial_conditions"], "langs": ["zh"]})

    assert result["ready"] is True
    assert result["blocked_reasons"] == []


def test_formal_release_checks_emit_no_body_rows(repo: Path, tmp_path: Path, monkeypatch):
    private_repo = tmp_path / "MOSAIC-Prompts"
    _init_private_prompt_repo_for_test(private_repo, repo)
    agents = {
        "us_financial_conditions": "macro",
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
        {"agents": ["us_financial_conditions"], "langs": ["zh"], "benchmark_run_id": "bench-release"},
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
        "us_financial_conditions", "macro", _MACRO_SCHEMA_FIELDS
    ).replace("<!-- cohort-behavior:start -->", "")
    _write_contract_prompt(private_repo, text=text)
    _git(private_repo, "add", "prompts/mosaic")
    _git(private_repo, "commit", "-m", "bad contract prompt")
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    result = dispatch("prompts.contract_check", {"agents": ["us_financial_conditions"], "langs": ["zh"]})

    assert result["ready"] is False
    assert "required_contract_missing:cohort_lens" in result["blocked_reasons"]


def test_contract_check_blocks_missing_schema_field(repo: Path, tmp_path: Path, monkeypatch):
    private_repo = tmp_path / "MOSAIC-Prompts"
    _init_private_prompt_repo_for_test(private_repo, repo)
    missing_field = _prompts._AGENT_SCHEMA_FIELDS["semiconductor"][0]
    fields = tuple(
        field
        for field in _prompts._AGENT_SCHEMA_FIELDS["semiconductor"]
        if field != missing_field
    )
    _write_contract_prompt(
        private_repo,
        agent="semiconductor",
        layer="sector",
        text=_valid_contract_prompt("semiconductor", "sector", fields),
    )
    _git(private_repo, "add", "prompts/mosaic")
    _git(private_repo, "commit", "-m", "schema drift prompt")
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    result = dispatch(
        "prompts.contract_check", {"agents": ["semiconductor"], "langs": ["zh"]}
    )

    assert result["ready"] is False
    assert f"schema_field_missing:{missing_field}" in result["blocked_reasons"]


def test_contract_check_blocks_rke_prior_as_current_data(
    repo: Path, tmp_path: Path, monkeypatch
):
    private_repo = tmp_path / "MOSAIC-Prompts"
    _init_private_prompt_repo_for_test(private_repo, repo)
    text = _valid_contract_prompt(
        "us_financial_conditions", "macro", _MACRO_SCHEMA_FIELDS
    ) + "\nCall get_rke_research_context as a production input."
    _write_contract_prompt(private_repo, text=text)
    _git(private_repo, "add", "prompts/mosaic")
    _git(private_repo, "commit", "-m", "unsafe rke prompt")
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    result = dispatch("prompts.contract_check", {"agents": ["us_financial_conditions"], "langs": ["zh"]})

    assert result["ready"] is False
    assert "production_rke_input_forbidden" in result["blocked_reasons"]
    assert (
        "unapproved_tool_mentioned:get_rke_research_context"
        in result["blocked_reasons"]
    )


def test_contract_check_blocks_cross_run_prompt_row(
    repo: Path, tmp_path: Path, monkeypatch
):
    private_repo = tmp_path / "MOSAIC-Prompts"
    _init_private_prompt_repo_for_test(private_repo, repo)
    _write_contract_prompt(private_repo)
    _git(private_repo, "add", "prompts/mosaic")
    _git(private_repo, "commit", "-m", "contract prompt")
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
    preflight = dispatch(
        "prompts.preflight", {"agents": ["us_financial_conditions"], "langs": ["zh"]}
    )
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
        "us_financial_conditions", "macro", _MACRO_SCHEMA_FIELDS
    )
    _write_contract_prompt(private_repo, lang="zh", text=good)
    _write_contract_prompt(
        private_repo,
        lang="en",
        text=good.replace("<!-- cohort-behavior:start -->", ""),
    )
    _git(private_repo, "add", "prompts/mosaic")
    _git(private_repo, "commit", "-m", "bilingual drift prompt")
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    result = dispatch(
        "prompts.contract_check",
        {"agents": ["us_financial_conditions"], "langs": ["zh", "en"]},
    )

    assert result["ready"] is False
    assert "bilingual_contract_category_drift" in result["blocked_reasons"]


def test_committed_bundled_prompts_follow_generated_runtime_contract():
    root = Path(__file__).resolve().parents[1]
    for agent, contract in _prompts._RUNTIME_PROMPT_CONTRACTS.items():
        layer = _prompts._LAYER_BY_AGENT[agent]
        for lang in ("zh", "en"):
            text = (
                root
                / "prompts"
                / "mosaic"
                / "cohort_default"
                / layer
                / f"{agent}.{lang}.md"
            ).read_text(encoding="utf-8")
            blockers, categories = _prompts._check_runtime_prompt_contract_text(
                agent, text
            )
            assert blockers == [], (agent, lang, blockers)
            assert all(categories.values()), (agent, lang, categories, contract)
