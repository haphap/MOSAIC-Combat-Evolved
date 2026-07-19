from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_bridge_docs_describe_capability_only_tool_surface():
    for path in ("docs/wiki/Bridge-RPC.md", "docs/wiki/zh/Bridge-RPC.md"):
        text = _read(path)
        assert "_TOOL_MODULES=()" in text
        assert "research_report_tools" not in text
        assert "tools.prepare_capability" in text
        assert "tools.terminate_capability" in text


def test_daily_cycle_docs_match_smoke_budget_and_private_fail_closed_policy():
    for path in ("docs/wiki/CLI-Reference.md", "docs/wiki/zh/CLI-Reference.md"):
        text = _read(path)
        assert "8192" in text
        assert "6144" not in text
        assert "bundled prompt" in text
        assert "fail closed" in text or "直接拒绝" in text
        assert "never fall back" in text or "绝不回退" in text
        assert "tool-call <name>" not in text


def test_advertised_fake_daily_cycle_builds_hash_bound_fixtures_first():
    for path in (
        "README.md",
        "docs/wiki/CLI-Reference.md",
        "docs/wiki/zh/CLI-Reference.md",
        "docs/wiki/Getting-Started.md",
        "docs/wiki/zh/Getting-Started.md",
        "docs/runbooks/mosaic_fish_feedback_loop.md",
    ):
        text = _read(path)
        assert "daily-cycle" in text and "--fake-llm" in text
        assert "build_structured_smoke_fixtures.py" in text
        assert "--shell-exports" in text
        assert 'SMOKE_DATE="${SMOKE_DATE:-2026-07-17}"' in text
        assert "date +%F" not in text


def test_chinese_home_keeps_report_intelligence_shadow_only():
    text = _read("docs/wiki/zh/Home.md")
    assert "RKE 研报只在 shadow 评测链使用" in text
    assert "行业 agent 用 Tushare 行业研报" not in text
