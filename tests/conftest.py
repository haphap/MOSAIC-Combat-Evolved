"""Test isolation for env vars that point at real external resources.

``mosaic/__init__`` calls ``load_dotenv()``, so a developer's ``.env`` bleeds
into the test process. Vars like ``MOSAIC_PROMPTS_REPO`` /
``MOSAIC_MIROFISH_URL`` would otherwise make tests operate on a real prompt repo
or MiroFish service. Clear them before each test; tests that need them set them
explicitly via ``monkeypatch.setenv`` (which runs after this autouse fixture).
"""

from __future__ import annotations

import json
import os
import fcntl
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest

_RKE_DEFAULT_TMPDIR = Path(
    os.environ.get("MOSAIC_RKE_TMPDIR") or "/home/hap/tmp/mosaic-rke"
).expanduser()
_RKE_DEFAULT_TMPDIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MOSAIC_RKE_TMPDIR", str(_RKE_DEFAULT_TMPDIR))
os.environ.setdefault("TMPDIR", str(_RKE_DEFAULT_TMPDIR))

_LEAK_VARS = (
    "MOSAIC_PROMPTS_REPO",
    "MOSAIC_PROMPTS_ROOT",
    "MOSAIC_PROMPTS_REPO_ID",
    "MOSAIC_PRIVATE_PROMPT_REPO",
    "MOSAIC_PRIVATE_PROMPT_REPO_ID",
    "MOSAIC_MIROFISH_URL",
    "MOSAIC_CHINA_POLICY_DB_DIR",
    "MOSAIC_CHINA_POLICY_DB_REPO_URL",
    "MOSAIC_CHINA_POLICY_DB_RAW_BASE_URL",
    "MOSAIC_CHINA_POLICY_DB_PUSH_UPDATES",
)

_RKE_MANUAL_REVIEW_SCRATCH = frozenset(
    {
        "gold_set_reviewed.jsonl",
        "gold_set_full_reviewed.jsonl",
        "gold_set_review_assist.jsonl",
        "gold_set_review_assist.md",
        "gold_set_review_evidence.jsonl",
        "gold_set_review_evidence.md",
        "analytical_footprint_review_assist.jsonl",
        "analytical_footprint_review_evidence.jsonl",
        "analytical_footprint_review_evidence.md",
        "analytical_footprint_review_workbook.md",
        "source_license_policy_reviewed.json",
        "source_license_policy_import.jsonl",
        "lockbox_reviewed.json",
    }
)
_RKE_TUSHARE_REGISTRY_COPY_SAMPLE_ROWS = 128
_RKE_TUSHARE_SOURCE_PATH = Path("sources/tushare_research_reports.jsonl")
_RKE_TUSHARE_MANIFEST_PATH = Path("sources/tushare_research_reports.manifest.json")
_RKE_TUSHARE_LICENSE_REVIEW_PATH = Path(
    "compliance/tushare_license_review_template.jsonl"
)
_RKE_TUSHARE_GOLD_CANDIDATES_PATH = Path(
    "sources/tushare_research_reports.gold_candidates.jsonl"
)
_RKE_TUSHARE_GOLD_REVIEW_PATH = Path(
    "gold_sets/tushare_research_reports.review_template.jsonl"
)
_RKE_SYNTHETIC_FIXTURE_PATHS = (
    Path("registry") / _RKE_TUSHARE_SOURCE_PATH,
    Path("registry") / _RKE_TUSHARE_MANIFEST_PATH,
    Path("registry") / _RKE_TUSHARE_LICENSE_REVIEW_PATH,
    Path("registry") / _RKE_TUSHARE_GOLD_CANDIDATES_PATH,
    Path("registry") / _RKE_TUSHARE_GOLD_REVIEW_PATH,
    Path("registry/gold_sets/tushare_research_reports.candidate_claims.jsonl"),
    Path("registry/gold_sets/tushare_research_reports.candidate_claims.summary.json"),
    Path("registry/gold_sets/tushare_research_reports.review_summary.json"),
    Path("registry/gold_sets/tushare_research_reports.review_import_report.json"),
    Path("registry/gold_sets/tushare_research_reports.review_packet.json"),
    Path("registry/gold_sets/tushare_research_reports.review_packet.md"),
    Path("registry/compliance/tushare_license_review_summary.json"),
    Path("registry/compliance/tushare_license_review_import_report.json"),
    Path("registry/compliance/tushare_license_review_packet.json"),
    Path("registry/compliance/tushare_license_review_packet.md"),
    Path("registry/source_checks/source_registry_validation_report.json"),
    Path("registry/report_intelligence/report_metadata.jsonl"),
    Path("registry/report_intelligence/processing_status.jsonl"),
    Path("registry/report_intelligence/forecast_claims.jsonl"),
    Path("registry/report_intelligence/analytical_footprints.jsonl"),
    Path("registry/report_intelligence/report_outcome_labels.jsonl"),
    Path("registry/report_intelligence/weighted_research_contexts.jsonl"),
)
_RKE_TRACKED_TEST_MUTABLE_PATHS = (
    Path("registry/dashboards/rke_dashboard.json"),
    Path("registry/dashboards/rke_dashboard.md"),
    Path("registry/review_batches/manual_review_bundle_manifest.json"),
    Path("registry/review_batches/manual_review_progress_report.json"),
    Path("registry/review_batches/manual_review_runbook.md"),
    Path("registry/review_batches/source_license_policy_import_report.json"),
    Path("registry/schemas/rke_schema_validation_report.json"),
)
_RKE_SYNTHETIC_TUSHARE_SOURCE_COUNT = 50
_RKE_SYNTHETIC_TUSHARE_CLAIMS_PER_SOURCE = 10
_RKE_SYNTHETIC_SEMICONDUCTOR_SOURCE_ID = "SRC-TSRR-SYNTH-20260601-0000"
_RKE_SYNTHETIC_DOMAINS = (
    "central_bank",
    "dollar",
    "volatility",
    "semiconductor",
    "other",
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )


def _git_status_porcelain(root_path: Path) -> set[str]:
    if not (root_path / ".git").exists():
        return set()
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root_path,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return set()
    return {line for line in result.stdout.splitlines() if line.strip()}


def _restore_paths_from_backups(
    root_path: Path,
    backups: list[tuple[Path, Path | None]],
) -> None:
    for relative_path, backup_path in backups:
        path = root_path / relative_path
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        if backup_path is None:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if backup_path.is_dir():
            shutil.copytree(backup_path, path)
        else:
            shutil.copy2(backup_path, path)


def _synthetic_source_id(index: int) -> str:
    if index == 0:
        return _RKE_SYNTHETIC_SEMICONDUCTOR_SOURCE_ID
    return f"SRC-TSRR-SYNTH-20260605-{index:04d}"


def _synthetic_source_hash(index: int) -> str:
    return f"sha256:synthetic-rke-fixture-{index:04d}"


def _synthetic_domain(index: int) -> str:
    return _RKE_SYNTHETIC_DOMAINS[index % len(_RKE_SYNTHETIC_DOMAINS)]


def _synthetic_domain_terms(domain: str) -> tuple[str, ...]:
    return {
        "central_bank": ("央行", "流动性", "利率"),
        "dollar": ("美元", "人民币汇率", "美联储"),
        "volatility": ("VIX", "风险偏好", "波动"),
        "semiconductor": ("半导体", "国产替代", "AI算力"),
        "other": ("订单", "盈利", "需求"),
    }[domain]


def _build_synthetic_tushare_rows() -> list[dict]:
    rows: list[dict] = []
    for index in range(_RKE_SYNTHETIC_TUSHARE_SOURCE_COUNT):
        domain = _synthetic_domain(index)
        terms = _synthetic_domain_terms(domain)
        source_id = _synthetic_source_id(index)
        abstract = (
            f"合成研报样本{index:03d}用于测试，不含真实研报原文。"
            f"{terms[0]}相关信号显示{terms[1]}改善，{terms[2]}带来阶段性催化。"
            "同时提示估值、价格、需求和风险需要用点时数据验证。"
        )
        if index == 0:
            abstract += (
                "半导体行业合成场景中，存储市场仍保持较高景气度；"
                "行业估值高于近年中枢水平；中美科技摩擦加剧。"
            )
        rows.append(
            {
                "abstract": abstract,
                "author": "synthetic-fixture",
                "discovered_at": "2026-06-05T00:00:00+00:00",
                "industry": "半导体" if index == 0 or domain == "semiconductor" else "合成行业",
                "institution": "Synthetic RKE Fixture",
                "license_status": "pending_review",
                "point_in_time_available": True,
                "publish_date": "2026-06-01" if index == 0 else "2026-06-05",
                "query_key": "半导体" if index == 0 or domain == "semiconductor" else terms[0],
                "report_type": "行业研报",
                "source_hash": _synthetic_source_hash(index),
                "source_id": source_id,
                "source_span_id": f"{source_id}:abstract",
                "source_type": "tushare_research_report",
                "title": f"Synthetic RKE research fixture {index:03d}.pdf",
                "ts_code": "",
                "url": "https://example.invalid/synthetic-rke-fixture.pdf",
            }
        )
    return rows


def _build_synthetic_gold_candidates(sources: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for index, source in enumerate(sources):
        domain = _synthetic_domain(index)
        terms = _synthetic_domain_terms(domain)
        domains = (domain,) if domain != "other" else ("other",)
        rows.append(
            {
                **source,
                "gold_set_domain": domain,
                "gold_set_domains": list(domains),
                "gold_set_domain_matches": (
                    {domain: list(terms[:2])} if domain != "other" else {}
                ),
                "gold_set_domain_scores": ({domain: 3} if domain != "other" else {}),
                "license_status": "approved",
            }
        )
    return rows


def _synthetic_claim_row(source: dict, document_index: int, claim_index: int) -> dict:
    source_id = str(source["source_id"])
    domain = _synthetic_domain(document_index)
    terms = _synthetic_domain_terms(domain)
    domain_matches = {domain: list(terms[:2])}
    domain_scores = {domain: 3}
    claim_text = (
        f"{terms[0]}驱动的合成测试观点{claim_index:02d}需要结合价格、"
        "成交和基本面窗口验证。"
    )
    claim_id = f"GOLD-{source_id}-{claim_index + 1:03d}"
    return {
        "candidate_available": True,
        "cause_variables": ["pboc_net_injection", "valuation_percentile"],
        "claim_id": claim_id,
        "claim_text": claim_text,
        "claim_type": "causal_mechanism",
        "direction": "positive",
        "extraction_confidence_bin": "medium",
        "gold_set_domain": domain,
        "gold_set_domains": [domain],
        "gold_set_domain_matches": domain_matches,
        "gold_set_domain_scores": domain_scores,
        "review_risk_flags": ["manual_review_required"],
        "source_end_char": min(len(str(source["abstract"])), 120),
        "source_id": source_id,
        "source_span_id": str(source["source_span_id"]),
        "source_span_ref_id": f"{source['source_span_id']}:candidate-{claim_index + 1:02d}",
        "source_start_char": 0,
        "source_text_hash": f"sha256:syntheticclaim{document_index:03d}{claim_index:03d}",
        "target_variables": ["industry_etf_forward_return"],
        "unsupported_fields": ["failure_modes", "valid_conditions"],
        "verifier_status": "requires_review",
    }


def _ensure_synthetic_private_tushare_registry(root_path: Path) -> None:
    source_path = root_path / "registry" / _RKE_TUSHARE_SOURCE_PATH
    ri_fixture_paths = (
        root_path / "registry/report_intelligence/report_metadata.jsonl",
        root_path / "registry/report_intelligence/processing_status.jsonl",
        root_path / "registry/report_intelligence/forecast_claims.jsonl",
        root_path / "registry/report_intelligence/analytical_footprints.jsonl",
        root_path / "registry/report_intelligence/report_outcome_labels.jsonl",
        root_path / "registry/report_intelligence/weighted_research_contexts.jsonl",
    )
    required_fixture_paths = [
        root_path / "registry" / _RKE_TUSHARE_SOURCE_PATH,
        root_path / "registry" / _RKE_TUSHARE_GOLD_CANDIDATES_PATH,
        root_path / "registry" / _RKE_TUSHARE_GOLD_REVIEW_PATH,
        root_path / "registry" / _RKE_TUSHARE_LICENSE_REVIEW_PATH,
        *ri_fixture_paths,
    ]
    if source_path.exists() and all(path.exists() for path in required_fixture_paths):
        return

    sources = _build_synthetic_tushare_rows()
    source_ids = {str(row["source_id"]) for row in sources}
    gold_candidates = _build_synthetic_gold_candidates(sources)
    candidate_claims = [
        _synthetic_claim_row(source, document_index, claim_index)
        for document_index, source in enumerate(sources)
        for claim_index in range(_RKE_SYNTHETIC_TUSHARE_CLAIMS_PER_SOURCE)
    ]
    review_rows = []
    for claim in candidate_claims:
        review_rows.append(
            {
                **claim,
                "document_id": claim["source_id"],
                "manual_claim_text": claim["claim_text"],
                "claim_correct": True,
                "source_span_supports_claim": True,
                "direction_correct": True,
                "target_correct": True,
                "horizon_correct": True,
                "variable_mapping_correct": True,
                "unsupported_field_false_grounded": False,
                "proposed_claim_text": claim["claim_text"],
                "proposed_claim_type": claim["claim_type"],
                "proposed_extraction_confidence_bin": claim[
                    "extraction_confidence_bin"
                ],
                "proposed_gold_set_domain": claim["gold_set_domain"],
                "proposed_gold_set_domains": claim["gold_set_domains"],
                "proposed_gold_set_domain_matches": claim[
                    "gold_set_domain_matches"
                ],
                "proposed_gold_set_domain_scores": claim["gold_set_domain_scores"],
                "proposed_direction": claim["direction"],
                "proposed_cause_variables": claim["cause_variables"],
                "proposed_target_variables": claim["target_variables"],
                "proposed_review_risk_flags": claim["review_risk_flags"],
                "proposed_source_start_char": claim["source_start_char"],
                "proposed_source_end_char": claim["source_end_char"],
                "proposed_source_span_ref_id": claim["source_span_ref_id"],
                "proposed_source_text_hash": claim["source_text_hash"],
                "proposed_verifier_status": claim["verifier_status"],
                "reviewer": "synthetic_fixture",
                "review_date": "2026-06-07",
                "review_notes": "synthetic fixture approval",
                "span_preview": "synthetic fixture preview",
            }
        )
    license_rows = [
        {
            "approved_for_derived_claim_storage": True,
            "approved_for_production_runtime": True,
            "current_license_status": "pending_review",
            "notes": "synthetic fixture approval",
            "publish_date": source["publish_date"],
            "review_date": "2026-06-07",
            "reviewer": "synthetic_fixture",
            "source_id": source["source_id"],
            "source_type": source["source_type"],
            "title": source["title"],
        }
        for source in sources
    ]

    _write_jsonl(source_path, sources)
    _write_jsonl(
        root_path / "registry" / _RKE_TUSHARE_GOLD_CANDIDATES_PATH,
        gold_candidates,
    )
    _write_jsonl(
        root_path / "registry/gold_sets/tushare_research_reports.candidate_claims.jsonl",
        candidate_claims,
    )
    _write_jsonl(root_path / "registry" / _RKE_TUSHARE_GOLD_REVIEW_PATH, review_rows)
    _write_jsonl(root_path / "registry" / _RKE_TUSHARE_LICENSE_REVIEW_PATH, license_rows)

    _write_json(
        root_path / "registry/sources/tushare_research_reports.manifest.json",
        {
            "corpus_id": "CORPUS-TSRR-SYNTHETIC-FIXTURE",
            "output_path": "registry/sources/tushare_research_reports.jsonl",
            "private_data_fixture": True,
            "row_count": len(sources),
            "rows_with_abstract": len(sources),
            "source": "synthetic_pytest_fixture",
        },
    )
    _write_json(
        root_path / "registry/gold_sets/tushare_research_reports.candidate_claims.summary.json",
        {
            "summary_id": "RKE-GOLD-CANDIDATE-CLAIMS-SUMMARY-SYNTHETIC",
            "candidate_claim_count": len(candidate_claims),
            "candidate_available_count": len(candidate_claims),
            "review_rows_with_candidate_fields": len(review_rows),
            "missing_variable_mapping_count": 0,
            "manual_fields_preserved": True,
            "risk_flag_counts": {"manual_review_required": len(candidate_claims)},
            "domain_counts": {
                domain: sum(1 for row in candidate_claims if row["gold_set_domain"] == domain)
                for domain in _RKE_SYNTHETIC_DOMAINS
            },
            "blockers": [],
        },
    )
    _write_json(
        root_path / "registry/gold_sets/tushare_research_reports.review_summary.json",
        {
            "summary_id": "RKE-GOLD-SET-REVIEW-SUMMARY-20260606",
            "review_path": "registry/gold_sets/tushare_research_reports.review_template.jsonl",
            "total_documents": len(sources),
            "total_claims": len(review_rows),
            "reviewed_claims": len(review_rows),
            "pending_claims": 0,
            "review_complete": True,
            "passed": True,
            "metrics": {
                "claim_precision": 1.0,
                "direction_accuracy": 1.0,
                "horizon_accuracy": 1.0,
                "source_span_support_precision": 1.0,
                "target_accuracy": 1.0,
                "unsupported_field_false_grounding_rate": 0.0,
                "variable_mapping_accuracy": 1.0,
            },
            "blockers": [],
        },
    )
    _write_json(
        root_path / "registry/compliance/tushare_license_review_summary.json",
        {
            "summary_id": "RKE-SOURCE-LICENSE-REVIEW-SUMMARY-20260606",
            "source_path": "registry/sources/tushare_research_reports.jsonl",
            "review_path": "registry/compliance/tushare_license_review_template.jsonl",
            "total_sources": len(sources),
            "total_review_rows": len(license_rows),
            "reviewed_sources": len(license_rows),
            "pending_sources": 0,
            "approved_for_production_runtime": len(license_rows),
            "review_complete": True,
            "passed": True,
            "blockers": [],
        },
    )
    _write_json(
        root_path / "registry/source_checks/source_registry_validation_report.json",
        {
            "report_id": "RKE-SOURCE-REGISTRY-VALIDATION-REPORT-20260606",
            "source_paths": [
                "registry/sources/central_bank_sources.jsonl",
                "registry/sources/tushare_research_reports.jsonl",
                "registry/sources/semiconductor_demo_sources.jsonl",
            ],
            "source_reference_count": len(sources) + 2,
            "unique_source_count": len(source_ids) + 1,
            "duplicate_reference_count": 1,
            "accepted_for_sandbox": True,
            "accepted_for_production": True,
            "failure_count": 0,
            "production_blocker_count": 0,
            "records": [],
        },
    )
    _write_json(
        root_path / "registry/gold_sets/tushare_research_reports.review_import_report.json",
        {
            "accepted": False,
            "applied_rows": 0,
            "blockers": ["manual review import file is empty"],
            "downstream_outputs": {},
            "dry_run": True,
            "duplicate_ids": [],
            "input_path": "registry/review_batches/gold_set_full_import_template.jsonl",
            "input_rows": 0,
            "invalid_rows": [],
            "missing_target_ids": [],
            "rejected_rows": 0,
            "report_id": "RKE-GOLD-SET-REVIEW-IMPORT-REPORT-20260606",
            "review_kind": "gold_set",
            "target_path": "registry/gold_sets/tushare_research_reports.review_template.jsonl",
        },
    )
    _write_json(
        root_path / "registry/compliance/tushare_license_review_import_report.json",
        {
            "accepted": False,
            "applied_rows": 0,
            "blockers": ["manual review import file is empty"],
            "downstream_outputs": {},
            "dry_run": True,
            "duplicate_ids": [],
            "input_path": "registry/review_batches/source_license_policy_import.jsonl",
            "input_rows": 0,
            "invalid_rows": [],
            "missing_target_ids": [],
            "rejected_rows": 0,
            "report_id": "RKE-SOURCE-LICENSE-REVIEW-IMPORT-REPORT-20260606",
            "review_kind": "source_license",
            "target_path": "registry/compliance/tushare_license_review_template.jsonl",
        },
    )
    ledger_path = root_path / "registry/report_intelligence/report_forecast_ledger.jsonl"
    ledger_rows: list[dict] = []
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                ledger_rows.append(row)
    if not ledger_rows:
        ledger_rows = [
            {
                "forecast_claim_id": "FC-SYNTH-RKE-0001",
                "forecast_family_id": "FF-SYNTH-RKE-0001",
                "report_id": "RPT-SYNTH-RKE-0001",
            }
        ]
    report_ids = sorted(
        {str(row.get("report_id") or "RPT-SYNTH-RKE-0001") for row in ledger_rows}
    )
    readiness_path = root_path / "registry/report_intelligence/outcome_labeling_readiness.json"
    proxy_label_ready_ids: set[str] = set()
    if readiness_path.exists():
        readiness_payload = json.loads(readiness_path.read_text(encoding="utf-8"))
        proxy_label_ready_ids = {
            str(claim_id)
            for claim_id in readiness_payload.get("proxy_label_ready_forecast_claim_ids", [])
            if str(claim_id).strip()
        }
    source_id = sources[0]["source_id"]
    source_span_id = sources[0]["source_span_id"]
    _write_jsonl(
        root_path / "registry/report_intelligence/report_metadata.jsonl",
        [
            {
                "report_id": report_id,
                "source_id": source_id,
                "institution_id": "INST-SYNTH-RKE",
                "author_ids": ["AUTHOR-SYNTH-RKE"],
                "report_type": "行业研报",
                "market": "CN",
                "asset_class": "equity",
                "sector": "semiconductor",
                "publish_datetime": "2026-06-01T00:00:00+00:00",
                "accessible_datetime": "2026-06-05T00:00:00+00:00",
                "license_class": "synthetic_test_fixture",
                "redistribution_allowed": False,
                "derived_claim_storage_allowed": "yes_synthetic_fixture",
                "point_in_time_available": True,
                "extraction": {
                    "backend": "synthetic_fixture",
                    "markdown_path": ".mosaic/rke/report_intelligence/markdown/synthetic.md",
                },
                "source_hash": sources[0]["source_hash"],
                "publish_date": sources[0]["publish_date"],
                "title": sources[0]["title"],
                "markdown": {"path": ".mosaic/rke/report_intelligence/markdown/synthetic.md"},
                "processing_status": "completed",
            }
            for report_id in report_ids
        ],
    )
    _write_jsonl(
        root_path / "registry/report_intelligence/processing_status.jsonl",
        [
            {
                "report_id": report_id,
                "source_id": source_id,
                "status": "completed",
                "backend": "synthetic_fixture",
                "error": "",
            }
            for report_id in report_ids
        ],
    )
    def synthetic_forecast_claim_for_ledger_row(row: dict) -> dict:
        claim_id = str(row.get("forecast_claim_id") or "")
        ready = str(row.get("test_status") or "") == "ready_for_outcome_labeling"
        base = {
            "forecast_claim_id": claim_id,
            "forecast_family_id": str(
                row.get("forecast_family_id") or "FF-SYNTH-RKE-0001"
            ),
            "claim_id": f"CLAIM-{claim_id or 'SYNTH'}",
            "report_id": str(row.get("report_id") or report_ids[0]),
            "source_id": source_id,
            "source_span_ids": [source_span_id],
            "claim_text": "合成研报认为半导体景气度需要结合点时数据验证。",
            "claim_provenance": "source_grounded",
            "forecast_type": "industry_view",
            "signal_datetime": "2026-06-05T00:00:00+00:00",
            "metric_proxy_mapping": ["industry_etf_forward_return"],
            "extractor": {"backend": "synthetic_fixture"},
        }
        if ready:
            return {
                **base,
                "forecast_testability": "testable",
                "target": {"target_type": "sector", "target_id": "半导体"},
                "benchmark": {"benchmark_symbol": "SH510300"},
                "direction": "positive",
                "horizon": {"window_days": 20},
                "failure_modes": [],
                "extraction_quality": {
                    "confidence": "medium",
                    "mapping_gaps": [],
                },
            }
        return {
            **base,
            "forecast_testability": "insufficient_mapping",
            "target": {},
            "benchmark": {},
            "direction": "unknown",
            "horizon": {},
            "failure_modes": [
                {
                    "text": "synthetic clean-checkout row keeps mapping gaps explicit",
                    "provenance": "source_grounded",
                }
            ],
            "extraction_quality": {
                "confidence": "medium",
                "mapping_gaps": ["target", "benchmark", "horizon"],
                "proxy_label_ready": claim_id in proxy_label_ready_ids,
            },
        }

    _write_jsonl(
        root_path / "registry/report_intelligence/forecast_claims.jsonl",
        [synthetic_forecast_claim_for_ledger_row(row) for row in ledger_rows],
    )
    _write_jsonl(
        root_path / "registry/report_intelligence/analytical_footprints.jsonl",
        [
            {
                "footprint_id": "RIFP-SYNTH-0001",
                "report_id": report_ids[0],
                "source_id": source_id,
                "source_span_ids": [source_span_id],
                "topic": "synthetic semiconductor fixture",
                "extraction_type": "source_grounded",
                "market": "CN",
                "sector": "semiconductor",
                "license_class": "synthetic_test_fixture",
                "storage_policy": "local_private_fixture_only",
                "extractor": {"backend": "synthetic_fixture"},
                "indicator_mentions": [
                    {
                        "name": "industry_etf_forward_return",
                        "source_grounded": True,
                        "source_span_ids": [source_span_id],
                    }
                ],
                "analysis_patterns": [
                    {
                        "name": "etf_window_validation",
                        "steps": ["map industry report to ETF proxy"],
                        "source_grounded": True,
                    }
                ],
                "target_agent_candidates": ["sector.semiconductor"],
                "target_entity_candidates": ["半导体"],
            }
        ],
    )
    _write_jsonl(
        root_path / "registry/report_intelligence/report_outcome_labels.jsonl",
        [],
    )
    _write_jsonl(
        root_path / "registry/report_intelligence/weighted_research_contexts.jsonl",
        [
            {
                "weighted_context_id": "RIRC-SYNTH-0001",
                "agent_id": "research.general",
                "as_of_datetime": "2026-06-05T00:00:00+00:00",
                "report_id": report_ids[0],
                "source_id": source_id,
                "retrieved_claims": [],
                "retrieved_footprints": [],
                "available_analysis_recipes": [],
                "tool_gaps": [],
                "research_only": True,
                "actionability": "no_trade_without_current_data_confirmation",
                "weight": 1.0,
                "reason": "synthetic fixture",
            }
        ],
    )
    from mosaic.rke.gold_review_packet import write_gold_review_packet
    from mosaic.rke.license_review_packet import write_license_review_packet

    write_gold_review_packet(root_path)
    write_license_review_packet(root_path)


@pytest.fixture(scope="session", autouse=True)
def _ensure_private_tushare_test_fixture(tmp_path_factory):
    root_path = Path.cwd()
    backup_root = tmp_path_factory.mktemp("rke-private-tushare-backup")
    moved_paths: list[tuple[Path, Path]] = []
    tmp_root = Path(
        os.environ.get("MOSAIC_RKE_TMPDIR") or "/home/hap/tmp/mosaic-rke"
    ).expanduser()
    tmp_root.mkdir(parents=True, exist_ok=True)
    lock_path = tmp_root / "mosaic-rke-private-tushare-fixture.lock"
    lock_handle = lock_path.open("w", encoding="utf-8")
    fcntl.flock(lock_handle, fcntl.LOCK_EX)

    def restore_private_paths() -> None:
        for relative_path in _RKE_SYNTHETIC_FIXTURE_PATHS:
            path = root_path / relative_path
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        for relative_path, backup_path in moved_paths:
            restore_path = root_path / relative_path
            if not backup_path.exists():
                continue
            restore_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(backup_path), str(restore_path))

    try:
        for relative_path in _RKE_SYNTHETIC_FIXTURE_PATHS:
            path = root_path / relative_path
            if not path.exists():
                continue
            backup_path = backup_root / relative_path
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(backup_path))
            moved_paths.append((relative_path, backup_path))

        before_status = _git_status_porcelain(root_path)
        _ensure_synthetic_private_tushare_registry(root_path)
        after_status = _git_status_porcelain(root_path)
        fixture_status_delta = sorted(after_status - before_status)
        assert not fixture_status_delta, (
            "synthetic private Tushare fixture must only write gitignored paths; "
            f"unexpected git status delta: {fixture_status_delta}"
        )
        yield
    finally:
        restore_private_paths()
        fcntl.flock(lock_handle, fcntl.LOCK_UN)
        lock_handle.close()


@pytest.fixture(scope="session", autouse=True)
def _restore_tracked_rke_public_artifacts_after_tests(
    tmp_path_factory,
    _ensure_private_tushare_test_fixture,
):
    """Let tests rewrite public reports without leaving generated diffs behind."""

    root_path = Path.cwd()
    backup_root = tmp_path_factory.mktemp("rke-public-artifact-backup")
    backups: list[tuple[Path, Path | None]] = []
    for relative_path in _RKE_TRACKED_TEST_MUTABLE_PATHS:
        path = root_path / relative_path
        if not path.exists():
            backups.append((relative_path, None))
            continue
        backup_path = backup_root / relative_path
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir():
            shutil.copytree(path, backup_path)
        else:
            shutil.copy2(path, backup_path)
        backups.append((relative_path, backup_path))

    try:
        yield
    finally:
        _restore_paths_from_backups(root_path, backups)


@pytest.fixture(autouse=True)
def _isolate_external_env(monkeypatch):
    for var in _LEAK_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MOSAIC_CHINA_POLICY_DB_AUTO_SYNC", "0")


@pytest.fixture(autouse=True)
def _ignore_rke_manual_review_scratch_in_registry_copies(monkeypatch):
    """Keep pytest registry copies free of reviewer scratch and huge private rows."""

    original_copytree = shutil.copytree
    project_registry_path = (Path.cwd() / "registry").resolve()

    def load_jsonl_objects(path: Path, *, strict: bool = True) -> list[dict]:
        rows: list[dict] = []
        if not path.exists():
            return rows
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    if strict:
                        raise
                    continue
                if isinstance(row, dict):
                    rows.append(row)
        return rows

    def write_jsonl(path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )

    def collect_source_ids(path: Path) -> set[str]:
        return {
            source_id
            for row in load_jsonl_objects(path, strict=False)
            if (source_id := str(row.get("source_id") or row.get("document_id") or ""))
        }

    def sample_copied_tushare_registry(
        src_registry_path: Path,
        dst_registry_path: Path,
    ) -> None:
        source_path = dst_registry_path / _RKE_TUSHARE_SOURCE_PATH
        source_source_path = src_registry_path / _RKE_TUSHARE_SOURCE_PATH
        if not source_source_path.exists():
            return

        keep_source_ids: set[str] = set()
        keep_source_ids.update(
            collect_source_ids(dst_registry_path / _RKE_TUSHARE_GOLD_CANDIDATES_PATH)
        )
        keep_source_ids.update(
            collect_source_ids(dst_registry_path / _RKE_TUSHARE_GOLD_REVIEW_PATH)
        )
        sources_dir = dst_registry_path / "sources"
        if sources_dir.exists():
            for path in sources_dir.glob("*.jsonl"):
                if path == source_path:
                    continue
                keep_source_ids.update(collect_source_ids(path))

        first_rows: list[dict] = []
        referenced_rows: list[dict] = []
        seen_source_ids: set[str] = set()
        source_row_count = 0
        with source_source_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                source_row_count += 1
                source_id = str(row.get("source_id") or "")
                if source_row_count <= _RKE_TUSHARE_REGISTRY_COPY_SAMPLE_ROWS:
                    first_rows.append(row)
                    if source_id:
                        keep_source_ids.add(source_id)
                        seen_source_ids.add(source_id)
                elif source_id and source_id in keep_source_ids and source_id not in seen_source_ids:
                    referenced_rows.append(row)
                    seen_source_ids.add(source_id)

        if source_row_count <= _RKE_TUSHARE_REGISTRY_COPY_SAMPLE_ROWS and source_path.exists():
            return

        sampled_sources = first_rows + referenced_rows
        write_jsonl(source_path, sampled_sources)

        license_path = dst_registry_path / _RKE_TUSHARE_LICENSE_REVIEW_PATH
        if license_path.exists():
            sampled_licenses = [
                row
                for row in load_jsonl_objects(license_path, strict=False)
                if str(row.get("source_id") or "") in keep_source_ids
            ]
            write_jsonl(license_path, sampled_licenses)

        manifest_path = dst_registry_path / _RKE_TUSHARE_MANIFEST_PATH
        manifest = {}
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            report_type_counts = Counter(
                str(row.get("report_type") or "")
                for row in sampled_sources
                if row.get("report_type")
            )
            query_key_counts = Counter(
                str(row.get("query_key") or "")
                for row in sampled_sources
                if row.get("query_key")
            )
            publish_dates = sorted(
                {
                    str(row.get("publish_date") or "")
                    for row in sampled_sources
                    if row.get("publish_date")
                }
            )
            manifest["row_count"] = len(sampled_sources)
            manifest["rows_with_abstract"] = sum(
                1 for row in sampled_sources if row.get("abstract")
            )
            manifest["report_type_counts"] = dict(sorted(report_type_counts.items()))
            manifest["query_key_counts"] = dict(sorted(query_key_counts.items()))
            if publish_dates:
                manifest["publish_date_min"] = publish_dates[0]
                manifest["publish_date_max"] = publish_dates[-1]
        manifest["row_count"] = len(sampled_sources)
        manifest["rows_with_abstract"] = sum(
            1 for row in sampled_sources if row.get("abstract")
        )
        manifest["sampled_for_pytest_registry_copy"] = True
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

    def copytree_without_review_scratch(
        src,
        dst,
        symlinks=False,
        ignore=None,
        copy_function=shutil.copy2,
        ignore_dangling_symlinks=False,
        dirs_exist_ok=False,
    ):
        effective_ignore = ignore
        src_path = Path(src).resolve()
        dst_parts = Path(dst).parts
        should_trim_registry_copy = src_path == project_registry_path
        should_ignore_review_scratch = should_trim_registry_copy and any(
            part == "pytest" or part.startswith("pytest-") for part in dst_parts
        )
        if should_ignore_review_scratch:
            original_ignore = ignore

            def ignore_review_scratch(dirname, names):
                ignored = set(original_ignore(dirname, names)) if original_ignore else set()
                ignored.update(name for name in names if name in _RKE_MANUAL_REVIEW_SCRATCH)
                dirname_path = Path(dirname).resolve()
                if dirname_path == project_registry_path / "sources":
                    ignored.add(_RKE_TUSHARE_SOURCE_PATH.name)
                return ignored

            effective_ignore = ignore_review_scratch

        copied_path = original_copytree(
            src,
            dst,
            symlinks=symlinks,
            ignore=effective_ignore,
            copy_function=copy_function,
            ignore_dangling_symlinks=ignore_dangling_symlinks,
            dirs_exist_ok=dirs_exist_ok,
        )
        if should_ignore_review_scratch:
            sample_copied_tushare_registry(src_path, Path(copied_path))
        return copied_path

    monkeypatch.setattr("shutil.copytree", copytree_without_review_scratch)
