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
