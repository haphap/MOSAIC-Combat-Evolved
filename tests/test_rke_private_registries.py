import json
import subprocess
from pathlib import Path

from mosaic.rke.cli import main
from mosaic.rke.private_registries import (
    build_report_fingerprint_manifest,
    export_private_registries,
    registries_preflight,
    resolve_report_intelligence_registry_dir,
)
from mosaic.rke.report_intelligence import (
    ReportIntelligenceConfig,
    run_report_intelligence_refresh,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_agent_context_registry(registry: Path) -> None:
    _write_jsonl(
        registry / "forecast_claims.jsonl",
        [
            {
                "forecast_claim_id": "FC-ENV",
                "report_id": "RPT-ENV",
                "target": {"target_type": "macro_series", "target_id": "USDCNY"},
                "direction": "positive",
            }
        ],
    )
    _write_jsonl(
        registry / "report_metadata.jsonl",
        [
            {
                "report_id": "RPT-ENV",
                "source_id": "SRC-ENV",
                "publish_datetime": "2026-01-01T00:00:00+08:00",
            }
        ],
    )
    for name in (
        "report_outcome_labels.jsonl",
        "source_performance_profiles.jsonl",
        "viewpoint_performance_profiles.jsonl",
        "analysis_recipes.jsonl",
        "tool_gaps.jsonl",
        "weighted_research_contexts.jsonl",
        "stock_context_snapshots.jsonl",
        "industry_context_snapshots.jsonl",
    ):
        _write_jsonl(registry / name, [])


def test_report_intelligence_registry_resolver_precedence(tmp_path, monkeypatch):
    monkeypatch.delenv("MOSAIC_REGISTRY_DIR", raising=False)
    monkeypatch.delenv("MOSAIC_REGISTRIES_REPO", raising=False)
    assert resolve_report_intelligence_registry_dir(tmp_path) == (
        tmp_path / "registry/report_intelligence"
    ).resolve()

    repo = tmp_path / "MOSAIC-Registries"
    monkeypatch.setenv("MOSAIC_REGISTRIES_REPO", str(repo))
    assert resolve_report_intelligence_registry_dir(tmp_path) == (
        repo / "registry/report_intelligence"
    ).resolve()

    env_dir = tmp_path / "env-registry"
    monkeypatch.setenv("MOSAIC_REGISTRY_DIR", str(env_dir))
    assert resolve_report_intelligence_registry_dir(tmp_path) == env_dir.resolve()

    explicit = tmp_path / "explicit-registry"
    assert resolve_report_intelligence_registry_dir(tmp_path, explicit) == explicit.resolve()


def test_fingerprint_manifest_is_stable_and_indexes_claims(tmp_path):
    registry = tmp_path / "registry/report_intelligence"
    _write_jsonl(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        [
            {
                "source_id": "SRC-1",
                "source_hash": "sha256:source",
                "title": "  Liquidity Cycle  ",
                "institution": "Inst",
                "author": "Alice,Bob",
                "publish_date": "2026-01-01",
                "url": "https://example.test/r.pdf",
            }
        ],
    )
    _write_jsonl(
        registry / "report_metadata.jsonl",
        [
            {
                "source_id": "SRC-1",
                "report_id": "RPT-1",
                "pdf": {"sha256": "sha256:pdf"},
                "markdown": {"sha256": "sha256:md"},
            }
        ],
    )
    _write_jsonl(
        registry / "forecast_claims.jsonl",
        [
            {
                "forecast_claim_id": "FC-1",
                "report_id": "RPT-1",
                "source_span_ids": ["SRC-1:p1"],
            }
        ],
    )
    _write_jsonl(
        registry / "analytical_footprints.jsonl",
        [
            {
                "footprint_id": "AFP-1",
                "report_id": "RPT-1",
                "source_span_ids": ["SRC-1:p2"],
            }
        ],
    )

    first = build_report_fingerprint_manifest(registry)
    second = build_report_fingerprint_manifest(registry)

    assert first == second
    assert first[0]["source_hash"] == "sha256:source"
    assert first[0]["pdf_sha256"] == "sha256:pdf"
    assert first[0]["markdown_sha256"] == "sha256:md"
    assert first[0]["forecast_claim_index"][0]["forecast_claim_id"] == "FC-1"
    assert first[0]["footprint_index"][0]["footprint_id"] == "AFP-1"


def test_export_private_registries_copies_json_not_cache(tmp_path):
    registry = tmp_path / "registry/report_intelligence"
    _write_jsonl(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        [{"source_id": "SRC-1", "source_hash": "sha256:source"}],
    )
    _write_jsonl(
        registry / "report_metadata.jsonl",
        [{"source_id": "SRC-1", "report_id": "RPT-1"}],
    )
    _write_jsonl(
        registry / "forecast_claims.jsonl",
        [{"source_id": "SRC-1", "report_id": "RPT-1", "forecast_claim_id": "FC-1"}],
    )
    _write_jsonl(registry / "analytical_footprints.jsonl", [])
    _write_jsonl(
        registry / "processing_status.jsonl",
        [{"source_id": "SRC-1", "llm_status": "processed"}],
    )
    cache_file = tmp_path / ".mosaic/rke/report_intelligence/pdfs/SRC-1.pdf"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"%PDF")

    out = tmp_path / "MOSAIC-Registries"
    result = export_private_registries(root=tmp_path, output_dir=out)

    assert result["accepted"] is True
    assert (out / "registry/report_intelligence/forecast_claims.jsonl").exists()
    assert (out / "registry/report_intelligence/report_fingerprint_manifest.jsonl").exists()
    assert (out / "registry/sources/tushare_research_reports.jsonl").exists()
    assert not (out / ".mosaic/rke/report_intelligence/pdfs/SRC-1.pdf").exists()
    manifest = json.loads((out / "registry_manifest.json").read_text(encoding="utf-8"))
    assert manifest["cache_manifest"]["included"] is False
    assert manifest["forecast_claim_count"] == 1

    subprocess.run(["git", "init", "-q"], cwd=out, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.invalid"],
        cwd=out,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "MOSAIC Tests"],
        cwd=out,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=out, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-qm", "fixture"],
        cwd=out,
        check=True,
        capture_output=True,
    )
    preflight = registries_preflight(root=tmp_path, registry_dir=out / "registry/report_intelligence")
    assert preflight["accepted"] is True
    assert preflight["blockers"] == []


def test_registries_preflight_reports_missing_dirty_and_duplicates(tmp_path, monkeypatch):
    missing = tmp_path / "missing"
    monkeypatch.setenv("MOSAIC_REGISTRIES_REPO", str(missing))
    missing_result = registries_preflight(root=tmp_path)
    assert missing_result["accepted"] is False
    assert "registries repo missing" in missing_result["blockers"]
    assert "registry_manifest.json missing" in missing_result["blockers"]

    repo = tmp_path / "MOSAIC-Registries"
    registry = repo / "registry/report_intelligence"
    _write_jsonl(
        registry / "report_fingerprint_manifest.jsonl",
        [
            {"source_id": "SRC-1", "report_id": "RPT-1", "source_hash": "sha256:a"},
            {"source_id": "SRC-1", "report_id": "RPT-2", "source_hash": "sha256:a"},
        ],
    )
    (repo / "registry_manifest.json").write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    (repo / "dirty.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("MOSAIC_REGISTRIES_REPO", str(repo))

    result = registries_preflight(root=tmp_path)

    assert result["accepted"] is False
    assert result["dirty"] is True
    assert result["dirty_blocker"] == "registries repo dirty"
    assert result["duplicate_fingerprint_count"] == 2
    assert result["manifest_hash"].startswith("sha256:")
    assert "registries repo dirty" in result["blockers"]
    assert any("required registry file missing" in item for item in result["blockers"])


def test_export_rke_agent_context_reads_env_registry(tmp_path, monkeypatch, capsys):
    registry = tmp_path / "MOSAIC-Registries/registry/report_intelligence"
    _write_agent_context_registry(registry)
    monkeypatch.setenv("MOSAIC_REGISTRY_DIR", str(registry))

    rc = main(("export-rke-agent-context", "--root", str(tmp_path), "--agent-id", "cio"))

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["item_count"] == 1


def test_merge_report_intelligence_batches_reads_env_registry(tmp_path, monkeypatch):
    registry = tmp_path / "MOSAIC-Registries/registry/report_intelligence"
    _write_jsonl(registry / "tool_gaps.jsonl", [{"tool_gap_id": "TG-0"}])
    batch = tmp_path / "batch"
    _write_jsonl(batch / "tool_gaps.jsonl", [{"tool_gap_id": "TG-1"}])
    monkeypatch.setenv("MOSAIC_REGISTRY_DIR", str(registry))

    rc = main(("merge-report-intelligence-batches", "--root", str(tmp_path), "--input-dir", str(batch)))

    assert rc == 0
    rows = [json.loads(line) for line in (registry / "tool_gaps.jsonl").read_text().splitlines()]
    assert [row["tool_gap_id"] for row in rows] == ["TG-0", "TG-1"]


def test_report_intelligence_skips_cloned_fingerprint_duplicates(tmp_path):
    source = {
        "source_id": "SRC-DUP",
        "source_hash": "sha256:dup",
        "title": "Duplicate",
        "institution": "Inst",
        "publish_date": "2026-01-01",
        "url": "https://example.test/dup.pdf",
    }
    _write_jsonl(tmp_path / "registry/sources/tushare_research_reports.jsonl", [source])
    registry = tmp_path / "registry/report_intelligence"
    _write_jsonl(
        registry / "report_fingerprint_manifest.jsonl",
        [
            {
                "source_id": "SRC-DUP",
                "report_id": "RPT-DUP",
                "source_hash": "sha256:dup",
                "institution_id": "INST-old",
                "publish_datetime": "2026-01-01T00:00:00+08:00",
                "title_normalized_hash": "sha256:title",
            }
        ],
    )

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            skip_download=True,
            skip_convert=True,
            skip_llm=True,
        )
    )

    assert result.selected_reports == 0
    status = [
        json.loads(line)
        for line in (registry / "processing_status.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert status[0]["source_id"] == "SRC-DUP"
    assert status[0]["blockers"] == ["duplicate_report_fingerprint:source_id"]
