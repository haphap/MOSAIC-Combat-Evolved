from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from mosaic.rke.cli import main
from mosaic.rke.registry_manifest import PRIVATE_LOCAL_REGISTRY_FILES
from mosaic.rke.report_intelligence import (
    DEFAULT_MINERU_ARGS_TEMPLATE,
    MineruBatchConversionTask,
    ReportIntelligenceConfig,
    REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS,
    build_report_intelligence_pit_leakage_audit,
    apply_analytical_footprint_review_import,
    build_confidence_impact_monitor,
    build_confidence_impact_observations,
    build_prompt_mutation_candidates,
    build_recipe_paper_trading_runs,
    build_recipe_paper_trading_summary,
    build_report_intelligence_extraction_provenance_audit,
    build_source_performance_profiles,
    build_viewpoint_performance_profiles,
    build_weighted_research_contexts,
    classify_tool_coverage,
    convert_pdfs_with_mineru_batch,
    run_report_intelligence_refresh,
    run_report_intelligence_derived_refresh,
)


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_source(
    path: Path,
    *,
    url: str = "https://example.invalid/report.pdf",
    industry: str = "宏观",
    report_type: str = "宏观研报",
    publish_date: str = "2026-06-05",
    ts_code: str = "",
) -> str:
    source_id = "SRC-TSRR-20260605-LIQUIDITY"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "abstract": "摘要不能作为本测试的抽取输入。",
                "author": "Analyst A",
                "discovered_at": "2026-06-06T00:00:00+00:00",
                "industry": industry,
                "institution": "Broker A",
                "license_status": "pending_review",
                "point_in_time_available": True,
                "publish_date": publish_date,
                "query_key": "liquidity",
                "report_type": report_type,
                "source_hash": "sha256:test",
                "source_id": source_id,
                "source_span_id": f"{source_id}:abstract",
                "source_type": "tushare_research_report",
                "title": "Liquidity report",
                "ts_code": ts_code,
                "url": url,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return source_id


def _write_qlib_series(
    root: Path,
    symbol: str,
    values: list[float],
    *,
    field: str = "adjclose",
    start_index: float = 0.0,
) -> None:
    if "." in symbol:
        code, market = symbol.split(".", 1)
        qlib_symbol = market.lower() + code
    else:
        qlib_symbol = symbol.lower()
    path = root / "features" / qlib_symbol / f"{field}.day.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack(f"<{len(values) + 1}f", start_index, *values))


def _write_qlib_calendar(root: Path, dates: list[str]) -> None:
    (root / "calendars").mkdir(parents=True, exist_ok=True)
    (root / "calendars/day.txt").write_text("\n".join(dates) + "\n", encoding="utf-8")


def _stock_fixture_dates() -> list[str]:
    dates = [f"2026-01-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-02-{day:02d}" for day in range(1, 29)]
    dates += [f"2026-03-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-04-{day:02d}" for day in range(1, 31)]
    dates += [f"2026-05-{day:02d}" for day in range(1, 32)]
    return dates


def _write_qlib_stock_fixture(
    root: Path,
    *,
    symbol: str = "000001.SZ",
    values: list[float] | None = None,
    volume: list[float] | None = None,
) -> None:
    dates = _stock_fixture_dates()
    _write_qlib_calendar(root, dates)
    if values is None:
        values = []
        for index in range(len(dates)):
            if index <= 2:
                values.append(1.0)
            elif index <= 7:
                values.append(1.0 - (index - 2) * 0.005)
            else:
                values.append(0.975 + (index - 7) * 0.004)
    volume_values = volume or [100.0 for _ in dates]
    for field, field_values in {
        "adjclose": values,
        "close": values,
        "open": values,
        "high": [value * 1.001 for value in values],
        "low": [value * 0.999 for value in values],
        "volume": volume_values,
    }.items():
        _write_qlib_series(root, symbol, field_values, field=field)


def _write_qlib_stock_entry_limit_locked_fixture(root: Path) -> None:
    dates = _stock_fixture_dates()
    _write_qlib_calendar(root, dates)
    values = [1.0 + index * 0.001 for index in range(len(dates))]
    entry_index = 2
    values[entry_index - 1] = 1.0
    values[entry_index] = 1.1
    open_values = list(values)
    high_values = [value * 1.001 for value in values]
    low_values = [value * 0.999 for value in values]
    close_values = list(values)
    for field_values in (open_values, high_values, low_values, close_values):
        field_values[entry_index] = 1.1
    for field, field_values in {
        "adjclose": values,
        "close": close_values,
        "open": open_values,
        "high": high_values,
        "low": low_values,
        "volume": [100.0 for _ in dates],
    }.items():
        _write_qlib_series(root, "000001.SZ", field_values, field=field)


def _write_qlib_stock_exit_limit_locked_fixture(root: Path) -> None:
    dates = _stock_fixture_dates()
    _write_qlib_calendar(root, dates)
    values = [1.0 + index * 0.001 for index in range(len(dates))]
    exit_index = 7
    values[exit_index - 1] = 1.0
    values[exit_index] = 0.9
    open_values = list(values)
    high_values = [value * 1.001 for value in values]
    low_values = [value * 0.999 for value in values]
    close_values = list(values)
    for field_values in (open_values, high_values, low_values, close_values):
        field_values[exit_index] = 0.9
    for field, field_values in {
        "adjclose": values,
        "close": close_values,
        "open": open_values,
        "high": high_values,
        "low": low_values,
        "volume": [100.0 for _ in dates],
    }.items():
        _write_qlib_series(root, "000001.SZ", field_values, field=field)


def _write_qlib_stock_truncated_fixture(root: Path) -> None:
    dates = _stock_fixture_dates()
    _write_qlib_calendar(root, dates)
    values = [1.0 + index * 0.001 for index in range(7)]
    for field, field_values in {
        "adjclose": values,
        "close": values,
        "open": values,
        "high": [value * 1.001 for value in values],
        "low": [value * 0.999 for value in values],
        "volume": [100.0 for _ in values],
    }.items():
        _write_qlib_series(root, "000001.SZ", field_values, field=field)


def _write_qlib_stock_benchmark_fixture(root: Path) -> None:
    stock_dates = _stock_fixture_dates()
    dates = ["2025-12-31", *stock_dates]
    _write_qlib_calendar(root, dates)
    values = [1.0 + index * 0.001 for index in range(len(dates))]
    _write_qlib_series(root, "SH510300", values)


def _write_misaligned_qlib_stock_benchmark_fixture(root: Path) -> None:
    stock_dates = _stock_fixture_dates()
    dates = ["2025-12-29", "2025-12-30", "2025-12-31", *stock_dates]
    _write_qlib_calendar(root, dates)
    values = [100.0 for _ in dates]
    values[dates.index("2026-01-03")] = 10.0
    values[dates.index("2026-01-08")] = 11.0
    _write_qlib_series(root, "SH510300", values)


def _write_qlib_etf_fixture(root: Path) -> None:
    (root / "calendars").mkdir(parents=True, exist_ok=True)
    dates = [f"2026-01-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-02-{day:02d}" for day in range(1, 29)]
    dates += [f"2026-03-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-04-{day:02d}" for day in range(1, 31)]
    dates += [f"2026-05-{day:02d}" for day in range(1, 32)]
    (root / "calendars/day.txt").write_text("\n".join(dates) + "\n", encoding="utf-8")
    _write_qlib_series(root, "SH512400", [1.00 + index * 0.002 for index in range(len(dates))])
    _write_qlib_series(root, "SH510300", [1.00 + index * 0.001 for index in range(len(dates))])


def _write_qlib_etf_without_benchmark_fixture(root: Path) -> None:
    (root / "calendars").mkdir(parents=True, exist_ok=True)
    dates = [f"2026-01-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-02-{day:02d}" for day in range(1, 29)]
    dates += [f"2026-03-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-04-{day:02d}" for day in range(1, 31)]
    dates += [f"2026-05-{day:02d}" for day in range(1, 32)]
    (root / "calendars/day.txt").write_text("\n".join(dates) + "\n", encoding="utf-8")
    _write_qlib_series(root, "SH512400", [1.00 + index * 0.002 for index in range(len(dates))])


def _write_qlib_etf_without_proxy_fixture(root: Path) -> None:
    (root / "calendars").mkdir(parents=True, exist_ok=True)
    dates = [f"2026-01-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-02-{day:02d}" for day in range(1, 29)]
    dates += [f"2026-03-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-04-{day:02d}" for day in range(1, 31)]
    dates += [f"2026-05-{day:02d}" for day in range(1, 32)]
    (root / "calendars/day.txt").write_text("\n".join(dates) + "\n", encoding="utf-8")
    _write_qlib_series(root, "SH510300", [1.00 + index * 0.001 for index in range(len(dates))])


def _write_qlib_etf_mixed_window_fixture(root: Path) -> None:
    (root / "calendars").mkdir(parents=True, exist_ok=True)
    dates = [f"2026-01-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-02-{day:02d}" for day in range(1, 29)]
    dates += [f"2026-03-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-04-{day:02d}" for day in range(1, 31)]
    dates += [f"2026-05-{day:02d}" for day in range(1, 32)]
    (root / "calendars/day.txt").write_text("\n".join(dates) + "\n", encoding="utf-8")
    values: list[float] = []
    for index in range(len(dates)):
        if index <= 25:
            values.append(1.00 - index * 0.002)
        else:
            values.append(0.95 + (index - 25) * 0.002)
    _write_qlib_series(root, "SH512400", values)
    _write_qlib_series(root, "SH510300", [1.00 + index * 0.0005 for index in range(len(dates))])


def _write_qlib_etf_bearish_fixture(root: Path) -> None:
    (root / "calendars").mkdir(parents=True, exist_ok=True)
    dates = [f"2026-01-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-02-{day:02d}" for day in range(1, 29)]
    dates += [f"2026-03-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-04-{day:02d}" for day in range(1, 31)]
    dates += [f"2026-05-{day:02d}" for day in range(1, 32)]
    (root / "calendars/day.txt").write_text("\n".join(dates) + "\n", encoding="utf-8")
    _write_qlib_series(root, "SH512400", [1.00 - index * 0.0015 for index in range(len(dates))])
    _write_qlib_series(root, "SH510300", [1.00 + index * 0.0002 for index in range(len(dates))])


def _fake_downloader(url: str, path: Path, overwrite: bool):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4 fake report")
    return {
        "status": "downloaded",
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha(path),
    }


def _fake_text_downloader(url: str, path: Path, overwrite: bool):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "【报告摘要】\r\n电子材料平台迎来结构性拐点。\r\n2026年公司经营有望改善。"
    path.write_bytes(text.encode("gb18030"))
    return {
        "status": "downloaded",
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha(path),
    }


def _fake_converter(pdf: Path, output_dir: Path, markdown: Path, overwrite: bool):
    assert pdf.exists()
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text(
        "\n".join(
            [
                "# 流动性脉冲",
                "报告原文讨论7日公开市场净投放，并用DR007与政策利率利差确认资金压力。",
                "若公开市场净投放改善且DR007回落，高 beta 风格相对沪深300可能占优。",
            ]
        ),
        encoding="utf-8",
    )
    return {
        "status": "converted",
        "path": str(markdown),
        "bytes": markdown.stat().st_size,
        "sha256": _sha(markdown),
    }


def _fake_llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
    assert "摘要不能作为本测试" not in chunk
    assert "7日公开市场净投放" in chunk
    return {
        "status": "ok",
        "model": "fake-vllm",
        "payload": {
            "forecast_claims": [
                {
                    "claim_text": "公开市场净投放改善且DR007回落时，高 beta 风格相对沪深300可能占优。",
                    "claim_provenance": "source_grounded",
                    "forecast_testability": "testable",
                    "forecast_type": "macro_regime_to_style_relative_direction",
                    "target": {
                        "target_type": "style_index",
                        "target_id": "CN_A_SHARE_HIGH_BETA",
                    },
                    "benchmark": {
                        "benchmark_type": "broad_index",
                        "benchmark_id": "CSI300",
                    },
                    "direction": "positive",
                    "horizon": {
                        "min_days": 5,
                        "max_days": 20,
                        "unit": "trading_day",
                    },
                    "explicitness": "explicit",
                    "source_conviction": "medium",
                    "metric_proxy_mapping": [
                        "pboc_net_injection_7d",
                        "dr007_policy_rate_spread",
                    ],
                    "failure_modes": ["资金面重新收紧"],
                    "extraction_quality": {"needs_human_review": False},
                }
            ],
            "analytical_footprints": [
                {
                    "topic": "liquidity_impulse_and_funding_stress_confirmation",
                    "indicator_mentions": [
                        {
                            "indicator_text": "7日公开市场净投放",
                            "canonical_metric_candidate": "pboc_net_injection_7d",
                            "data_source_mentioned": "PBOC open market operation announcement",
                            "frequency": "daily",
                            "lookback_window": {
                                "value": 7,
                                "unit": "trading_day",
                            },
                            "transformation": "rolling_sum",
                            "role_in_argument": "liquidity_condition_proxy",
                            "source_grounded": True,
                        },
                        {
                            "indicator_text": "DR007与政策利率利差",
                            "canonical_metric_candidate": "dr007_policy_rate_spread",
                            "data_source_mentioned": "interbank repo market",
                            "frequency": "daily",
                            "lookback_window": {
                                "value": 20,
                                "unit": "trading_day",
                            },
                            "transformation": "zscore",
                            "role_in_argument": "funding_stress_confirmation",
                            "source_grounded": True,
                        },
                    ],
                    "analysis_patterns": [
                        {
                            "pattern_candidate": "liquidity_impulse_confirmation",
                            "steps": [
                                "calculate pboc_net_injection_7d",
                                "check dr007_policy_rate_spread",
                            ],
                        }
                    ],
                    "target_agent_candidates": ["macro.central_bank"],
                }
            ],
            "metric_candidates": [],
            "method_patterns": [],
            "tool_gaps": [],
        },
    }


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _git_ls_files(prefix: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", prefix],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _copy_committed_report_intelligence_public_artifacts(tmp_path: Path) -> Path:
    registry = tmp_path / "registry/report_intelligence"
    for relative in _git_ls_files("registry/report_intelligence"):
        if relative in REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS:
            continue
        source = Path(relative)
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return registry


def _iter_json_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _iter_json_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_json_keys(item)


def _read_committed_json_artifact(path: Path):
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return json.loads(text)


def test_private_report_intelligence_outputs_are_gitignored():
    assert set(REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS) <= PRIVATE_LOCAL_REGISTRY_FILES

    result = subprocess.run(
        ["git", "check-ignore", *sorted(REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS)],
        check=False,
        capture_output=True,
        text=True,
    )

    ignored = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    assert ignored == set(REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS)


def test_committed_report_intelligence_outputs_do_not_store_private_text_fields():
    forbidden_fields = {
        "abstract",
        "claim_text",
        "manual_claim_text",
        "source_span_id",
        "source_span_ids",
        "source_text",
        "source_text_hash",
        "span_preview",
    }
    leaked: list[str] = []
    for relative in _git_ls_files("registry/report_intelligence"):
        if relative in REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS:
            continue
        payload = _read_committed_json_artifact(Path(relative))
        present = set(_iter_json_keys(payload)) & forbidden_fields
        if present:
            leaked.append(f"{relative}: {sorted(present)}")

    assert not leaked


def test_report_intelligence_derived_refresh_refuses_clean_checkout_overwrite(
    tmp_path: Path,
):
    registry = _copy_committed_report_intelligence_public_artifacts(tmp_path)
    ledger_path = registry / "report_forecast_ledger.jsonl"
    readiness_path = registry / "outcome_labeling_readiness.json"
    before_ledger = ledger_path.read_text(encoding="utf-8")
    before_readiness = readiness_path.read_text(encoding="utf-8")

    result = run_report_intelligence_derived_refresh(
        ReportIntelligenceConfig(root=tmp_path, refresh_derived_only=True)
    )

    assert result.blocker_count == 1
    assert "private report-intelligence inputs missing" in result.blockers[0]
    assert ledger_path.read_text(encoding="utf-8") == before_ledger
    assert readiness_path.read_text(encoding="utf-8") == before_readiness


def test_report_intelligence_uses_original_markdown_and_writes_loop_artifacts(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )

    assert result.blocker_count == 0
    assert result.selected_reports == 1
    assert result.pdf_ready_count == 1
    assert result.markdown_ready_count == 1
    assert result.llm_processed_reports == 1
    assert result.forecast_claim_rows == 1
    assert result.analytical_footprint_rows == 1
    assert result.metric_candidate_rows == 2
    assert result.tool_gap_rows == 1
    assert result.forecast_ledger_rows == 1
    assert result.outcome_label_rows == 0
    assert result.tool_coverage_match_rows == 2
    assert result.data_acquisition_proposal_rows == 1
    assert result.tool_design_proposal_rows == 1
    assert result.analysis_recipe_rows == 1
    assert result.prompt_mutation_candidate_rows >= 1
    assert result.weighted_research_context_rows == 1
    assert result.runtime_tool_gap_observation_rows == 1
    assert result.outcome_labeling_ready_count == 1
    assert result.outcome_labeling_blocked_count == 0
    assert "runtime_safety_audit" in result.outputs
    assert "pit_leakage_audit" in result.outputs
    assert "extraction_provenance_audit" in result.outputs
    assert "statistical_robustness_audit" in result.outputs
    assert "tool_feasibility_audit" in result.outputs
    assert "recipe_validation_audit" in result.outputs
    assert "patch_v1_5_coverage_report" in result.outputs
    assert "recipe_paper_trading_runs" in result.outputs
    assert "recipe_paper_trading_summary" in result.outputs
    assert "confidence_impact_observations" in result.outputs
    assert "confidence_impact_monitor" in result.outputs
    assert "prompt_mutation_candidates" in result.outputs
    assert "markdown_coverage_summary" in result.outputs
    assert "industry_etf_proxy_map" in result.outputs
    assert "industry_etf_proxy_pit_availability" in result.outputs

    metadata = _read_jsonl(tmp_path / "registry/report_intelligence/report_metadata.jsonl")
    assert metadata[0]["source_id"] == source_id
    assert metadata[0]["version"] == "original_pdf_markdown"
    assert metadata[0]["extraction"]["abstract_only_fallback_used"] is False
    assert metadata[0]["extraction"]["llm_model"] == "fake-vllm"
    assert metadata[0]["source_row_license_status"] == "pending_review"
    assert metadata[0]["license_class"] == "operator_approved_internal_research_use"

    markdown_coverage = json.loads(
        (
            tmp_path / "registry/report_intelligence/markdown_coverage_summary.json"
        ).read_text(encoding="utf-8")
    )
    assert markdown_coverage["selected_report_count"] == 1
    assert markdown_coverage["markdown_ready_count"] == 1
    assert markdown_coverage["markdown_quality_pass_count"] == 1
    assert markdown_coverage["report_type_counts"] == {"宏观研报": 1}
    coverage_dump = json.dumps(markdown_coverage, ensure_ascii=False)
    assert source_id not in coverage_dump
    assert "Liquidity report" not in coverage_dump
    assert "https://example.invalid/report.pdf" not in coverage_dump

    forecasts = _read_jsonl(tmp_path / "registry/report_intelligence/forecast_claims.jsonl")
    assert forecasts[0]["source_span_ids"] == [
        f"{source_id}:original_markdown:chunk-001"
    ]
    assert forecasts[0]["claim_provenance"] == "source_grounded"
    assert forecasts[0]["failure_modes"] == [
        {
            "provenance": "analyst_or_llm_hypothesis",
            "requires_independent_validation": True,
            "text": "资金面重新收紧",
        }
    ]

    footprint_review = _read_jsonl(
        tmp_path
        / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    )
    assert len(footprint_review) == 1
    assert footprint_review[0]["review_kind"] == "analytical_footprint_gold_set"
    assert footprint_review[0]["manual_review_required"] is True
    assert footprint_review[0]["footprint_correct"] is None
    assert footprint_review[0]["metric_mapping_correct"] is None
    assert footprint_review[0]["target_row_hash"].startswith("sha256:")
    assert footprint_review[0]["indicator_mentions_review_preview"][0][
        "canonical_metric_candidate"
    ] == "pboc_net_injection_7d"

    footprint_review_summary = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/analytical_footprint_review_summary.json"
        ).read_text(encoding="utf-8")
    )
    assert footprint_review_summary["accepted"] is False
    assert footprint_review_summary["review_complete"] is False
    assert footprint_review_summary["quality_gate_passed"] is False
    assert footprint_review_summary["total_rows"] == 1
    assert footprint_review_summary["pending_rows"] == 1
    assert (
        footprint_review_summary["precision_recall_report"]["recall_status"]
        == "requires_human_negative_examples"
    )
    assert "analytical footprint review rows still pending" in " ".join(
        footprint_review_summary["blockers"]
    )

    footprint_taxonomy = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/analytical_footprint_error_taxonomy.json"
        ).read_text(encoding="utf-8")
    )
    assert {
        "hallucinated_metric",
        "ambiguous_metric_not_unknown",
        "proprietary_text_leakage",
    } <= {row["tag"] for row in footprint_taxonomy["error_tags"]}

    metrics = _read_jsonl(tmp_path / "registry/report_intelligence/metric_candidates.jsonl")
    coverage = {row["canonical_name"]: row["current_tool_coverage"] for row in metrics}
    assert coverage["pboc_net_injection_7d"] == "exact_match"
    assert coverage["dr007_policy_rate_spread"] == "partial_match"

    ledger = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_forecast_ledger.jsonl"
    )
    assert ledger[0]["test_status"] == "ready_for_outcome_labeling"
    assert ledger[0]["immutable"] is True

    outcome_labels = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"
    )
    assert outcome_labels == []

    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["ready_for_outcome_labeling_count"] == 1
    assert readiness["blocked_count"] == 0
    assert readiness["mapping_gap_counts"] == {}

    feature_flags = json.loads(
        (tmp_path / "registry/report_intelligence/feature_flags.json").read_text(
            encoding="utf-8"
        )
    )
    assert feature_flags["rollout_mode"] == "shadow_tooling"
    assert feature_flags["flags"]["weighted_research_retriever_enabled"] is True
    assert feature_flags["flags"]["shadow_tool_runtime_enabled"] is True
    assert feature_flags["flags"]["production_use_of_weighted_reports"] is False
    assert "no agent decision impact" in feature_flags["runtime_behavior"]

    coverage_matches = _read_jsonl(
        tmp_path / "registry/report_intelligence/tool_coverage_matches.jsonl"
    )
    coverage_by_metric = {
        row["metric_candidate_id"]: row["coverage_status"]
        for row in coverage_matches
    }
    metric_ids = {row["canonical_name"]: row["metric_candidate_id"] for row in metrics}
    assert coverage_by_metric[metric_ids["pboc_net_injection_7d"]] == "exact_match"
    assert coverage_by_metric[metric_ids["dr007_policy_rate_spread"]] == "partial_match"

    tool_gaps = _read_jsonl(tmp_path / "registry/report_intelligence/tool_gaps.jsonl")
    assert tool_gaps[0]["priority_bucket"] == "high"
    assert "missing_or_partial_data_blocks_named_agent" in tool_gaps[0][
        "priority_reasons"
    ]
    assert tool_gaps[0]["owner"] == "data_engineering"

    data_proposals = _read_jsonl(
        tmp_path / "registry/report_intelligence/data_acquisition_proposals.jsonl"
    )
    assert data_proposals[0]["decision_status"] == "pending_review"
    assert data_proposals[0]["owner"] == "data_engineering"
    assert data_proposals[0]["license_status"] == "pending_review"
    assert data_proposals[0]["pit_feasibility_status"] == (
        "pit_feasible_pending_vendor_review"
    )
    assert data_proposals[0]["source_tool_gap_priority"] == "high"

    tool_proposals = _read_jsonl(
        tmp_path / "registry/report_intelligence/tool_design_proposals.jsonl"
    )
    assert tool_proposals[0]["status"] == "shadow_build_requested"
    assert tool_proposals[0]["owner"] == "data_engineering"
    assert tool_proposals[0]["license_status"] == "pending_review"
    assert tool_proposals[0]["pit_feasibility_status"] == (
        "pit_feasible_pending_vendor_review"
    )
    assert tool_proposals[0]["engineering_estimate"] == "high"

    recipes = _read_jsonl(tmp_path / "registry/report_intelligence/analysis_recipes.jsonl")
    assert recipes[0]["runtime_mode"] == "shadow_only"

    weighted_contexts = _read_jsonl(
        tmp_path / "registry/report_intelligence/weighted_research_contexts.jsonl"
    )
    assert weighted_contexts[0]["research_only"] is True
    assert (
        weighted_contexts[0]["actionability"]
        == "no_trade_without_current_data_confirmation"
    )
    weighted_claim = weighted_contexts[0]["retrieved_claims"][0]
    assert weighted_claim["forecast_family_id"] == ledger[0]["forecast_family_id"]
    assert weighted_claim["consensus_cluster_id"] == ledger[0]["consensus_cluster_id"]
    assert weighted_claim["dedup_cluster_id"] == ledger[0]["dedup_cluster_id"]
    assert (
        weighted_claim["independent_confirmation_policy"]
        == "consensus_cluster_not_independent_confirmation"
    )
    assert weighted_claim["current_tool_evidence_ids"] == []

    runtime_gaps = _read_jsonl(
        tmp_path / "registry/report_intelligence/runtime_tool_gap_observations.jsonl"
    )
    assert runtime_gaps[0]["suggested_tool_gap_id"] == data_proposals[0]["tool_gap_id"]
    assert runtime_gaps[0]["runtime_role"] == "gap_observation_only"
    assert runtime_gaps[0]["research_only"] is True
    assert runtime_gaps[0]["allowed_runtime_mode"] == "shadow_only"
    assert runtime_gaps[0]["current_data_confirmation"] == "missing"
    assert (
        runtime_gaps[0]["actionability"]
        == "no_trade_without_current_data_confirmation"
    )

    runtime_safety = json.loads(
        (
            tmp_path / "registry/report_intelligence/runtime_safety_audit.json"
        ).read_text(encoding="utf-8")
    )
    assert runtime_safety["accepted"] is True
    assert runtime_safety["blocker_count"] == 0
    assert {row["check_id"] for row in runtime_safety["checks"]} == {
        f"RI-SAFE-{index:02d}" for index in range(10)
    }
    assert (
        "sector_score"
        in runtime_safety["checks"][3]["evidence"]["forbidden_fields"]
    )
    assert (
        runtime_safety["checks"][7]["evidence"]["consensus_cluster_count"] == 1
    )

    pit_audit = json.loads(
        (
            tmp_path / "registry/report_intelligence/pit_leakage_audit.json"
        ).read_text(encoding="utf-8")
    )
    assert pit_audit["accepted"] is True
    assert pit_audit["blocker_count"] == 0
    assert {row["check_id"] for row in pit_audit["checks"]} == {
        f"RI-PIT-{index:02d}" for index in range(8)
    }
    assert pit_audit["checks"][1]["evidence"]["forecast_claim_rows"] == 1
    assert pit_audit["checks"][2]["evidence"]["outcome_label_rows"] == 0

    provenance_audit = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/extraction_provenance_audit.json"
        ).read_text(encoding="utf-8")
    )
    assert provenance_audit["accepted"] is True
    assert provenance_audit["blocker_count"] == 0
    assert {row["check_id"] for row in provenance_audit["checks"]} == {
        f"RI-PROV-{index:02d}" for index in range(6)
    }
    assert (
        provenance_audit["checks"][1]["evidence"]["source_grounded_claim_count"]
        == 1
    )
    assert (
        provenance_audit["checks"][2]["evidence"][
            "source_grounded_or_mixed_footprint_count"
        ]
        == 1
    )

    statistical_audit = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/statistical_robustness_audit.json"
        ).read_text(encoding="utf-8")
    )
    assert statistical_audit["accepted"] is True
    assert statistical_audit["blocker_count"] == 0
    assert {row["check_id"] for row in statistical_audit["checks"]} == {
        f"RI-STAT-{index:02d}" for index in range(8)
    }
    assert statistical_audit["checks"][1]["evidence"]["outcome_label_rows"] == 0
    assert (
        statistical_audit["checks"][7]["evidence"]["fdr_or_reality_check_status"]
        == "deferred_until_paper_trading_or_production_candidate"
    )

    tool_feasibility_audit = json.loads(
        (
            tmp_path / "registry/report_intelligence/tool_feasibility_audit.json"
        ).read_text(encoding="utf-8")
    )
    assert tool_feasibility_audit["accepted"] is True
    assert tool_feasibility_audit["blocker_count"] == 0
    assert {row["check_id"] for row in tool_feasibility_audit["checks"]} == {
        f"RI-TOOL-{index:02d}" for index in range(7)
    }
    assert tool_feasibility_audit["checks"][1]["evidence"][
        "metric_candidate_rows"
    ] == 2
    assert tool_feasibility_audit["checks"][2]["evidence"][
        "non_exact_coverage_rows"
    ] == 1
    assert tool_feasibility_audit["checks"][4]["evidence"][
        "minimum_shadow_runtime_days"
    ] == 60

    recipe_validation_audit = json.loads(
        (
            tmp_path / "registry/report_intelligence/recipe_validation_audit.json"
        ).read_text(encoding="utf-8")
    )
    assert recipe_validation_audit["accepted"] is True
    assert recipe_validation_audit["blocker_count"] == 0
    assert {row["check_id"] for row in recipe_validation_audit["checks"]} == {
        f"RI-RECIPE-{index:02d}" for index in range(8)
    }
    assert recipe_validation_audit["checks"][1]["evidence"][
        "analysis_recipe_rows"
    ] == 1
    assert recipe_validation_audit["checks"][2]["evidence"][
        "validation_status_counts"
    ] == {"candidate": 1}
    assert recipe_validation_audit["checks"][4]["evidence"][
        "validation_candidate_recipe_count"
    ] == 0

    monitoring = json.loads(
        (tmp_path / "registry/report_intelligence/monitoring_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert monitoring["report_corpus"]["forecast_claim_rows"] == 1
    assert monitoring["report_weighting_monitoring"][
        "weighted_vs_unweighted_retrieval_difference"
    ] == 0.0
    assert monitoring["tooling_loop_monitoring"]["tool_gap_open_count"] == 1
    assert monitoring["tooling_loop_monitoring"][
        "runtime_fallback_observation_count"
    ] == 1
    assert monitoring["rollout_mode"] == "shadow_tooling"
    alpha_decay = monitoring["alpha_decay_monitoring"]
    assert alpha_decay["monitoring_spec_ready"] is True
    assert alpha_decay["alpha_decay_monitor_ready"] is True
    assert alpha_decay["live_alpha_decay_monitor_active"] is False
    assert alpha_decay["blocked_reason"] == "no_live_production_recipe_current_rollout"
    assert {
        "rolling_after_cost_alpha",
        "calibration_drift",
        "current_vs_backtest_performance_divergence",
    } <= set(alpha_decay["required_decay_metrics"])
    assert {
        "soft_rollback",
        "hard_rollback",
        "compliance_rollback",
    } <= set(alpha_decay["required_rollback_modes"])

    patch_coverage = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/patch_v1_5_coverage_report.json"
        ).read_text(encoding="utf-8")
    )
    assert patch_coverage["phase_count"] == 8
    assert patch_coverage["source_plan_path"] == (
        "MOSAIC_RKE_REPORT_INTELLIGENCE_LOOP_PATCH_V1_5_MERGED.md"
    )
    assert "/home/hap" not in json.dumps(patch_coverage, ensure_ascii=False)
    assert {row["phase_id"] for row in patch_coverage["phase_records"]} == set("ABCDEFGH")
    assert patch_coverage["phase_records"][0]["status"] == "passed"
    assert patch_coverage["phase_records"][1]["status"] == "blocked"
    assert patch_coverage["deferred_phase_ids"] == ["G", "H"]
    assert {
        row["phase_id"]: row["status"]
        for row in patch_coverage["phase_records"]
        if row["phase_id"] in {"G", "H"}
    } == {"G": "deferred_by_rollout", "H": "deferred_by_rollout"}
    assert alpha_decay["unmonitored_production_recipe_ids"] == []
    confidence_monitoring = monitoring["confidence_impact_monitoring"]
    assert confidence_monitoring["observation_count"] == 1
    assert confidence_monitoring["paper_trading_validated_recipe_count"] == 0
    assert confidence_monitoring["production_decision_impact_allowed"] is False

    paper_trading_runs = _read_jsonl(
        tmp_path
        / "registry/report_intelligence/recipe_paper_trading_runs.jsonl"
    )
    assert len(paper_trading_runs) == 1
    assert paper_trading_runs[0]["paper_trading_status"] == "blocked"
    assert paper_trading_runs[0]["production_decision_impact_allowed"] is False
    assert {
        "no_direct_recipe_outcome_binding",
        "insufficient_effective_n",
    } <= set(paper_trading_runs[0]["blocked_reasons"])

    confidence_observations = _read_jsonl(
        tmp_path
        / "registry/report_intelligence/confidence_impact_observations.jsonl"
    )
    assert confidence_observations[0]["confidence_delta"] == 0.0
    assert confidence_observations[0]["drift_status"] == "paper_trading_blocked"
    assert confidence_observations[0]["recommended_action"] == "keep_shadow"

    prompt_candidates = _read_jsonl(
        tmp_path
        / "registry/report_intelligence/prompt_mutation_candidates.jsonl"
    )
    assert prompt_candidates
    assert {
        "recipe_paper_trading_rule",
        "confidence_gate_rule",
        "tool_gap_prioritization_rule",
    } <= {row["candidate_type"] for row in prompt_candidates}
    assert all(row["production_prompt_change_allowed"] is False for row in prompt_candidates)
    assert all(row["private_text_included"] is False for row in prompt_candidates)
    candidate_dump = json.dumps(prompt_candidates, ensure_ascii=False)
    assert "claim_text" not in candidate_dump
    assert "source_span_ids" not in candidate_dump
    assert source_id not in candidate_dump


def test_report_intelligence_recipe_paper_trading_requires_direct_pit_evidence():
    recipe = {
        "analysis_recipe_id": "RECIPE-DIRECT-PIT",
        "method_pattern_id": "METHOD-DIRECT-PIT",
        "version": "0.1.0",
        "runtime_mode": "shadow_only",
        "required_tools": ["market.price_proxy"],
        "steps": [{"step": 1, "tool": "market.price_proxy"}],
        "output_signal": {"name": "direct_pit_score"},
    }
    labels = []
    for day, value, hit in (
        (10, 0.01, True),
        (11, 0.02, False),
        (12, 0.015, True),
        (13, 0.018, False),
        (14, 0.02, True),
    ):
        labels.append(
            {
                "analysis_recipe_id": "RECIPE-DIRECT-PIT",
                "method_pattern_id": "METHOD-DIRECT-PIT",
                "exit_datetime": f"2026-01-{day:02d}",
                "directional_after_cost_return": value,
                "benchmark_return": 0.005,
                "directional_hit": hit,
                "horizon_days": 20,
                "effective_n_weight": 1.0,
            }
        )

    runs = build_recipe_paper_trading_runs(
        run_id="RIR-TEST-PAPER",
        analysis_recipe_rows=[recipe],
        outcome_label_rows=labels,
        method_performance_profile_rows=[],
    )
    summary = build_recipe_paper_trading_summary(
        run_id="RIR-TEST-PAPER",
        recipe_paper_trading_runs=runs,
    )
    observations = build_confidence_impact_observations(
        run_id="RIR-TEST-PAPER",
        recipe_paper_trading_runs=runs,
    )
    monitor = build_confidence_impact_monitor(
        run_id="RIR-TEST-PAPER",
        confidence_observation_rows=observations,
        recipe_paper_trading_summary=summary,
    )

    assert runs[0]["paper_trading_status"] == "passed"
    assert runs[0]["blocked_reasons"] == []
    assert runs[0]["profile_weight_support"]["profile_only_validation_allowed"] is False
    assert summary["validation_pass_count"] == 1
    assert observations[0]["confidence_delta"] > 0
    assert observations[0]["drift_status"] == "stable_shadow"
    assert monitor["paper_trading_validated_recipe_count"] == 1
    assert monitor["production_decision_impact_allowed"] is False

    blocked_runs = build_recipe_paper_trading_runs(
        run_id="RIR-TEST-PAPER",
        analysis_recipe_rows=[recipe],
        outcome_label_rows=[],
        method_performance_profile_rows=[
            {
                "method_pattern_id": "METHOD-DIRECT-PIT",
                "method_profile_id": "MPP-DIRECT-PIT",
                "source_support": {"n_effective_reports": 5.0},
            }
        ],
    )
    blocked_observations = build_confidence_impact_observations(
        run_id="RIR-TEST-PAPER",
        recipe_paper_trading_runs=blocked_runs,
    )

    assert blocked_runs[0]["paper_trading_status"] == "blocked"
    assert "no_direct_recipe_outcome_binding" in blocked_runs[0]["blocked_reasons"]
    assert (
        blocked_runs[0]["profile_weight_support"][
            "profile_paper_trade_disagreement"
        ]
        is True
    )
    assert blocked_observations[0]["confidence_delta"] == 0.0
    assert blocked_observations[0]["drift_status"] == "paper_trading_blocked"


def test_report_intelligence_prompt_mutation_candidates_track_calibration_drift():
    candidates = build_prompt_mutation_candidates(
        run_id="RIR-TEST-MUTATION",
        outcome_labeling_readiness={
            "mapping_gap_counts": {},
            "stock_price_proxy_readiness": {"data_gap_counts": {}},
            "industry_etf_proxy_readiness": {"data_gap_counts": {}},
        },
        tool_gap_rows=[],
        recipe_paper_trading_runs=[],
        confidence_impact_observation_rows=[
            {
                "recipe_id": "RECIPE-DECAY",
                "paper_trading_status": "passed",
                "drift_status": "alpha_decay_watch",
                "recommended_action": "reduce_confidence_impact",
                "confidence_delta": 0.0,
            }
        ],
        confidence_impact_monitor={
            "drift_status_counts": {"alpha_decay_watch": 1},
            "recommended_action_counts": {"reduce_confidence_impact": 1},
        },
        markdown_coverage_summary={"markdown_quality_gap_counts": {}},
        industry_etf_proxy_pit_availability={"pit_gap_counts": {}},
    )

    calibration = [
        row for row in candidates if row["candidate_type"] == "calibration_fix_required"
    ]
    assert len(calibration) == 1
    assert calibration[0]["target_component"] == "confidence_calibration_policy"
    assert calibration[0]["production_prompt_change_allowed"] is False
    assert calibration[0]["private_text_included"] is False


def test_report_intelligence_can_select_historical_sources_by_date(
    tmp_path: Path,
):
    source_path = tmp_path / "registry/sources/tushare_research_reports.jsonl"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for source_id, publish_date in (
        ("SRC-TSRR-20260102-NEW", "2026-01-02"),
        ("SRC-TSRR-20250203-OLD", "2025-02-03"),
        ("SRC-TSRR-20250304-MID", "2025-03-04"),
    ):
        rows.append(
            {
                "abstract": "historical report",
                "author": "Analyst A",
                "discovered_at": "2026-06-06T00:00:00+00:00",
                "industry": "有色金属",
                "institution": "Broker A",
                "license_status": "pending_review",
                "point_in_time_available": True,
                "publish_date": publish_date,
                "query_key": "有色金属",
                "report_type": "行业研报",
                "source_hash": f"sha256:{source_id.lower()}",
                "source_id": source_id,
                "source_span_id": f"{source_id}:abstract",
                "source_type": "tushare_research_report",
                "title": f"Historical report {source_id}",
                "ts_code": "",
                "url": "https://example.invalid/report.pdf",
            }
        )
    _write_jsonl(source_path, rows)

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            limit=1,
            min_publish_date="2025-01-01",
            max_publish_date="2025-12-31",
            selection_order="oldest",
            skip_download=True,
            skip_convert=True,
            skip_llm=True,
        )
    )

    metadata = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_metadata.jsonl"
    )
    assert result.selected_reports == 1
    assert metadata[0]["source_id"] == "SRC-TSRR-20250203-OLD"


def test_extraction_provenance_allows_governed_industry_etf_proxy_outcomes():
    audit = build_report_intelligence_extraction_provenance_audit(
        run_id="RIR-TEST",
        forecast_rows=[
            {
                "forecast_claim_id": "FC-INDUSTRY-1",
                "claim_provenance": "source_grounded",
                "source_span_ids": ["SRC-1:original_markdown:chunk-001"],
                "forecast_testability": "not_testable",
                "direction": "positive",
                "target": {"target_type": "sector", "target_id": "有色金属"},
                "horizon": {"max_days": 120, "unit": "trading_day"},
            }
        ],
        footprint_rows=[],
        metric_rows=[],
        forecast_ledger_rows=[
            {
                "forecast_claim_id": "FC-INDUSTRY-1",
                "test_status": "blocked_mapping_missing",
            }
        ],
        outcome_label_rows=[
            {
                "forecast_claim_id": "FC-INDUSTRY-1",
                "label_type": "industry_etf_proxy",
                "outcome_label_source": "pit_industry_etf_price_window",
                "llm_outcome_labeling_allowed": False,
                "decision_basis": "absolute_proxy_return_direction",
            }
        ],
        outcome_labeling_readiness={
            "ready_for_outcome_labeling_count": 0,
            "standard_blocked_count": 1,
            "blocked_count": 0,
        },
    )

    by_id = {row["check_id"]: row for row in audit["checks"]}
    assert audit["accepted"] is True
    assert by_id["RI-PROV-04"]["accepted"] is True
    assert by_id["RI-PROV-04"]["evidence"][
        "industry_etf_proxy_outcome_claim_count"
    ] == 1


def test_report_intelligence_labels_industry_claims_with_etf_proxy_windows(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="工业金属",
        report_type="行业研究",
        publish_date="2026-01-02",
    )
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "有色金属行业景气度改善，板块后续有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {
                            "target_type": "sector",
                            "target_id": "工业金属",
                        },
                        "benchmark": {
                            "benchmark_type": "broad_index",
                            "benchmark_id": "CSI300",
                        },
                        "direction": "positive",
                        "horizon": {
                            "min_days": 20,
                            "max_days": 120,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.outcome_label_rows == 3
    assert result.industry_etf_proxy_outcome_label_rows == 3
    assert result.industry_etf_proxy_eligible_claim_rows == 1
    assert result.industry_etf_proxy_labelable_window_rows == 3
    assert result.industry_etf_proxy_pending_window_rows == 0

    outcome_labels = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"
    )
    assert {row["horizon_days"] for row in outcome_labels} == {20, 60, 120}
    assert {row["label_type"] for row in outcome_labels} == {"industry_etf_proxy"}
    assert {row["proxy_symbol"] for row in outcome_labels} == {"SH512400"}
    assert {row["benchmark_symbol"] for row in outcome_labels} == {"SH510300"}
    assert {row["benchmark_source"] for row in outcome_labels} == {"cn_etf"}
    assert {row["benchmark_family"] for row in outcome_labels} == {
        "CSI300_ETF_PROXY"
    }
    assert {row["cost_model_id"] for row in outcome_labels} == {
        "industry_etf_round_trip_10bps_v1"
    }
    assert all(str(row["mapping_id"]).startswith("IETF-MAP-") for row in outcome_labels)
    assert {row["mapping_version"] for row in outcome_labels} == {1}
    assert {row["pit_availability_status"] for row in outcome_labels} == {"available"}
    assert {row["decision_basis"] for row in outcome_labels} == {
        "absolute_proxy_return_direction"
    }
    assert {row["outcome_label_source"] for row in outcome_labels} == {
        "pit_industry_etf_price_window"
    }
    assert {row["llm_outcome_labeling_allowed"] for row in outcome_labels} == {False}
    assert {row["source_horizon_days"] for row in outcome_labels} == {120}
    assert {row["source_horizon_bucket"] for row in outcome_labels} == {
        "long_horizon"
    }
    assert {row["claim_window_alignment"] for row in outcome_labels} == {
        "within_source_horizon"
    }
    assert {row["evaluation_policy"] for row in outcome_labels} == {
        "industry_etf_t_plus_1_multi_window_proxy_retains_long_horizon_evidence"
    }
    assert {row["entry_datetime"] for row in outcome_labels} == {
        "2026-01-03T00:00:00+08:00"
    }
    assert {row["entry_lag_trading_days"] for row in outcome_labels} == {1}
    assert {row["round_trip_cost"] for row in outcome_labels} == {0.001}
    assert all(row["directional_hit"] is True for row in outcome_labels)
    assert all(row["relative_alpha"] > 0 for row in outcome_labels)

    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    proxy_readiness = readiness["industry_etf_proxy_readiness"]
    assert proxy_readiness["eligible_claim_count"] == 1
    assert proxy_readiness["labelable_forecast_claim_count"] == 1
    assert proxy_readiness["labelable_forecast_claim_ids"] == [
        outcome_labels[0]["forecast_claim_id"]
    ]
    assert proxy_readiness["labelable_window_count"] == 3
    assert proxy_readiness["pending_future_window_count"] == 0
    assert proxy_readiness["latest_calendar_date"] == "2026-05-31"
    assert proxy_readiness["entry_lag_trading_days"] == 1
    assert readiness["ready_for_outcome_labeling_count"] == 1
    assert readiness["standard_blocked_count"] == 0
    assert readiness["proxy_label_ready_count"] == 1
    assert readiness["proxy_label_only_ready_count"] == 0

    mapping_rows = _read_jsonl(
        tmp_path / "registry/report_intelligence/industry_etf_proxy_map.jsonl"
    )
    assert any(row["sector_name"] == "工业金属" for row in mapping_rows)
    assert {row["status"] for row in mapping_rows} == {"primary"}

    pit_availability = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/industry_etf_proxy_pit_availability.json"
        ).read_text(encoding="utf-8")
    )
    assert pit_availability["mapping_count"] == len(mapping_rows)
    industrial_metals = next(
        row for row in pit_availability["mapping_records"] if row["sector_name"] == "工业金属"
    )
    assert industrial_metals["pit_available"] is True
    assert industrial_metals["available_window_days"] == [20, 60, 120]
    availability_dump = json.dumps(pit_availability, ensure_ascii=False)
    assert source_id not in availability_dump
    assert "Liquidity report" not in availability_dump
    assert readiness["blocked_count"] == 0


def test_report_intelligence_industry_pit_availability_records_missing_benchmark(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="工业金属",
        report_type="行业研究",
        publish_date="2026-01-02",
    )
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_without_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "有色金属行业景气度改善，板块后续有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {
                            "target_type": "sector",
                            "target_id": "工业金属",
                        },
                        "benchmark": {
                            "benchmark_type": "broad_index",
                            "benchmark_id": "CSI300",
                        },
                        "direction": "positive",
                        "horizon": {
                            "min_days": 20,
                            "max_days": 120,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.industry_etf_proxy_outcome_label_rows == 0
    assert result.industry_etf_proxy_eligible_claim_rows == 1
    assert result.industry_etf_proxy_labelable_window_rows == 0

    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["industry_etf_proxy_readiness"]["data_gap_counts"] == {
        "benchmark_series_missing": 1
    }
    assert readiness["industry_proxy_label_ready_count"] == 0
    assert readiness["proxy_label_ready_count"] == 0

    pit_availability = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/industry_etf_proxy_pit_availability.json"
        ).read_text(encoding="utf-8")
    )
    assert pit_availability["pit_gap_counts"]["benchmark_series_missing"] >= 1
    labelability = pit_availability["labelability_summary"]
    assert labelability["eligible_claim_count"] == 1
    assert labelability["labelable_claim_count"] == 0
    assert labelability["labelable_window_count"] == 0
    assert labelability["benchmark_series_missing_count"] == 1
    assert labelability["data_gap_counts"] == {"benchmark_series_missing": 1}


def test_report_intelligence_industry_readiness_records_missing_proxy_series(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="工业金属",
        report_type="行业研究",
        publish_date="2026-01-02",
    )
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_without_proxy_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "有色金属行业景气度改善，板块后续有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {
                            "target_type": "sector",
                            "target_id": "工业金属",
                        },
                        "benchmark": {
                            "benchmark_type": "broad_index",
                            "benchmark_id": "CSI300",
                        },
                        "direction": "positive",
                        "horizon": {
                            "min_days": 20,
                            "max_days": 120,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.industry_etf_proxy_outcome_label_rows == 0
    assert result.industry_etf_proxy_eligible_claim_rows == 1
    assert result.industry_etf_proxy_labelable_window_rows == 0

    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["industry_etf_proxy_readiness"]["data_gap_counts"] == {
        "proxy_series_missing": 1
    }
    assert readiness["industry_proxy_label_ready_count"] == 0

    pit_availability = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/industry_etf_proxy_pit_availability.json"
        ).read_text(encoding="utf-8")
    )
    labelability = pit_availability["labelability_summary"]
    assert labelability["eligible_claim_count"] == 1
    assert labelability["labelable_claim_count"] == 0
    assert labelability["proxy_series_missing_count"] == 1
    assert labelability["data_gap_counts"] == {"proxy_series_missing": 1}


def test_report_intelligence_industry_candidate_mapping_does_not_label(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="工业金属",
        report_type="行业研究",
        publish_date="2026-01-02",
    )
    _write_jsonl(
        tmp_path / "registry/report_intelligence/industry_etf_proxy_map.jsonl",
        [
            {
                "mapping_id": "IETF-MAP-CANDIDATE-INDUSTRIAL-METALS",
                "mapping_version": 1,
                "sector_name": "工业金属",
                "sector_aliases": ["工业金属", "有色金属"],
                "taxonomy": "test_taxonomy",
                "etf_symbol": "SH512400",
                "etf_name": "有色金属ETF",
                "mapping_label": "有色金属ETF",
                "benchmark_symbol": "SH510300",
                "benchmark_source": "cn_etf",
                "benchmark_family": "CSI300_ETF_PROXY",
                "cost_model_id": "industry_etf_round_trip_10bps_v1",
                "mapping_confidence": "candidate_requires_review",
                "mapping_rationale": "candidate mappings must not label by default",
                "effective_from": "",
                "effective_to": "",
                "status": "candidate",
                "review_required": True,
            }
        ],
    )
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "有色金属行业景气度改善，板块后续有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {
                            "target_type": "sector",
                            "target_id": "工业金属",
                        },
                        "benchmark": {
                            "benchmark_type": "broad_index",
                            "benchmark_id": "CSI300",
                        },
                        "direction": "positive",
                        "horizon": {
                            "min_days": 20,
                            "max_days": 120,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.industry_etf_proxy_outcome_label_rows == 0
    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["industry_etf_proxy_readiness"]["data_gap_counts"] == {
        "sector_etf_mapping_missing": 1
    }
    assert readiness["industry_proxy_label_ready_count"] == 0


def test_report_intelligence_pit_audit_rejects_t0_industry_etf_entry():
    audit = build_report_intelligence_pit_leakage_audit(
        run_id="RIR-PIT-T0-TEST",
        feature_flags={
            "rollout_mode": "shadow_tooling",
            "flags": {"production_use_of_weighted_reports": False},
        },
        metadata_rows=[
            {
                "source_id": "SRC-T0",
                "accessible_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_rows=[
            {
                "forecast_claim_id": "FC-T0",
                "source_id": "SRC-T0",
                "signal_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_ledger_rows=[
            {
                "forecast_claim_id": "FC-T0",
                "as_of_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        outcome_label_rows=[
            {
                "outcome_id": "OUT-T0",
                "forecast_claim_id": "FC-T0",
                "entry_datetime": "2026-01-02T00:00:00+08:00",
                "exit_datetime": "2026-01-22T00:00:00+08:00",
                "pit_valid": True,
                "survivorship_safe": True,
                "label_type": "industry_etf_proxy",
                "entry_lag_trading_days": 0,
            }
        ],
        source_performance_profile_rows=[],
        tool_coverage_match_rows=[],
        analysis_recipe_rows=[],
        weighted_research_context_rows=[],
    )

    assert audit["accepted"] is False
    assert any("entry_datetime must be after signal date" in item for item in audit["blockers"])
    assert any("entry_lag_trading_days" in item for item in audit["blockers"])


def test_report_intelligence_labels_stock_claims_with_qlib_price_windows(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_stock_fixture(qlib_stock_dir)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来一个季度股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {
                            "target_type": "stock",
                            "target_id": "000001.SZ",
                            "target_name": "平安银行",
                            "target_price": {
                                "value": "1.02 CNY",
                                "provenance": "source_grounded",
                            },
                        },
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {
                            "min_days": 5,
                            "max_days": 120,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 4
    assert result.stock_price_proxy_eligible_claim_rows == 1
    assert result.stock_price_proxy_labelable_window_rows == 4

    outcome_labels = sorted(
        _read_jsonl(tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"),
        key=lambda row: row["horizon_days"],
    )
    assert {row["label_type"] for row in outcome_labels} == {"stock_price_proxy"}
    assert [row["horizon_days"] for row in outcome_labels] == [5, 20, 60, 120]
    assert [row["effective_n_weight"] for row in outcome_labels] == [
        0.2,
        0.25,
        0.25,
        0.3,
    ]
    assert {row["proxy_symbol"] for row in outcome_labels} == {"000001.SZ"}
    assert {row["benchmark_symbol"] for row in outcome_labels} == {"SH510300"}
    assert {row["benchmark_source"] for row in outcome_labels} == {"cn_etf"}
    assert {row["benchmark_alignment"] for row in outcome_labels} == {
        "date_key_cross_qlib_dir"
    }
    assert {row["cost_model_id"] for row in outcome_labels} == {
        "single_stock_round_trip_20bps_v1"
    }
    assert {row["outcome_label_source"] for row in outcome_labels} == {
        "pit_stock_price_window"
    }
    assert {row["llm_outcome_labeling_allowed"] for row in outcome_labels} == {False}
    assert {row["entry_datetime"] for row in outcome_labels} == {
        "2026-01-03T00:00:00+08:00"
    }
    assert {row["entry_lag_trading_days"] for row in outcome_labels} == {1}
    assert {row["round_trip_cost"] for row in outcome_labels} == {0.002}
    assert {row["target_resolution_source"] for row in outcome_labels} == {
        "metadata_and_llm_target_id"
    }
    assert {row["survivorship_safe"] for row in outcome_labels} == {False}
    assert {row["survivorship_check"] for row in outcome_labels} == {
        "survivorship_unverified_qlib_cn_data"
    }
    assert outcome_labels[0]["stock_return"] < 0
    assert outcome_labels[0]["directional_hit"] is False
    assert outcome_labels[0]["target_price_hit"] is False
    assert outcome_labels[-1]["stock_return"] > 0
    assert outcome_labels[-1]["directional_hit"] is True
    assert outcome_labels[-1]["target_price_hit"] is True
    assert {row["target_price"] for row in outcome_labels} == {1.02}
    assert {row["target_price_source_grounded"] for row in outcome_labels} == {True}
    assert {row["target_price_provenance"] for row in outcome_labels} == {
        "source_grounded"
    }
    assert outcome_labels[-1]["directional_after_cost_return"] > 0
    assert outcome_labels[0]["temporal_validation_summary"][
        "temporal_validation_bucket"
    ] == "short_miss_long_hit"

    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    stock_readiness = readiness["stock_price_proxy_readiness"]
    assert stock_readiness["eligible_claim_count"] == 1
    assert stock_readiness["labelable_forecast_claim_count"] == 1
    assert stock_readiness["labelable_window_count"] == 4
    assert stock_readiness["data_gap_counts"] == {}
    assert stock_readiness["pit_realism_policy"]["survivorship_unverified"] is True
    assert (
        stock_readiness["pit_realism_policy"]["survivorship_status"]
        == "survivorship_unverified"
    )
    assert readiness["stock_proxy_label_ready_count"] == 1
    assert readiness["proxy_label_ready_count"] == 1
    assert readiness["blocked_count"] == 0

    statistical_audit = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/statistical_robustness_audit.json"
        ).read_text(encoding="utf-8")
    )
    assert statistical_audit["accepted"] is True
    assert statistical_audit["checks"][1]["evidence"][
        "stock_price_proxy_label_rows"
    ] == 4
    assert statistical_audit["checks"][3]["evidence"][
        "complete_stock_price_window_set_count"
    ] == 1
    assert statistical_audit["checks"][6]["evidence"][
        "short_miss_long_hit_window_set_count"
    ] == 1


def test_report_intelligence_counts_stock_price_proxy_as_labelable_channel(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_stock_fixture(qlib_stock_dir)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.outcome_labeling_ready_count == 0
    assert result.outcome_labeling_blocked_count == 0
    assert result.stock_price_proxy_outcome_label_rows == 4
    assert result.stock_price_proxy_eligible_claim_rows == 1
    assert result.stock_price_proxy_labelable_window_rows == 4

    forecasts = _read_jsonl(
        tmp_path / "registry/report_intelligence/forecast_claims.jsonl"
    )
    forecast_claim_id = forecasts[0]["forecast_claim_id"]
    assert forecasts[0]["forecast_testability"] == "insufficient_mapping"
    assert forecasts[0]["extraction_quality"]["mapping_gaps"] == [
        "benchmark",
        "horizon",
    ]

    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["standard_blocked_count"] == 1
    assert readiness["standard_blocked_forecast_claim_ids"] == [forecast_claim_id]
    assert readiness["proxy_label_ready_count"] == 1
    assert readiness["stock_proxy_label_ready_count"] == 1
    assert readiness["industry_proxy_label_ready_count"] == 0
    assert readiness["stock_proxy_label_ready_forecast_claim_ids"] == [
        forecast_claim_id
    ]
    assert readiness["proxy_label_only_ready_count"] == 1
    assert readiness["blocked_count"] == 0
    assert readiness["unlabelable_mapping_gap_counts"] == {}


def test_report_intelligence_stock_benchmark_aligns_by_date_across_qlib_dirs(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_stock_fixture(qlib_stock_dir)
    _write_misaligned_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来五个交易日股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {"max_days": 5, "unit": "trading_day"},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 4
    outcome_labels = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"
    )
    five_day_label = next(row for row in outcome_labels if row["horizon_days"] == 5)
    assert five_day_label["entry_datetime"] == "2026-01-03T00:00:00+08:00"
    assert five_day_label["exit_datetime"] == "2026-01-08T00:00:00+08:00"
    assert five_day_label["benchmark_alignment"] == "date_key_cross_qlib_dir"
    assert five_day_label["benchmark_calendar_source"] == str(qlib_etf_dir)
    assert five_day_label["stock_calendar_source"] == str(qlib_stock_dir)
    assert five_day_label["benchmark_return"] == pytest.approx(0.1)


def test_report_intelligence_labels_bearish_stock_claims(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    dates = _stock_fixture_dates()
    _write_qlib_stock_fixture(
        qlib_stock_dir,
        values=[1.0 - index * 0.002 for index in range(len(dates))],
    )
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行盈利承压，未来一个季度股价可能下跌。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "negative",
                        "horizon": {"max_days": 120, "unit": "trading_day"},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 4
    outcome_labels = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"
    )
    assert {row["direction_evaluated"] for row in outcome_labels} == {"negative"}
    assert all(row["stock_return"] < 0 for row in outcome_labels)
    assert all(row["directional_stock_return"] > 0 for row in outcome_labels)
    assert all(row["directional_hit"] is True for row in outcome_labels)
    assert all(row["relative_directional_hit"] is True for row in outcome_labels)


def test_report_intelligence_stock_readiness_records_price_gaps(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_calendar(qlib_stock_dir, _stock_fixture_dates())
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 0
    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["stock_price_proxy_readiness"]["data_gap_counts"] == {
        "stock_series_missing": 1
    }
    assert readiness["blocked_count"] == 1


def test_report_intelligence_stock_target_conflict_blocks_labeling(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_stock_fixture(qlib_stock_dir)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000002.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 0
    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["stock_price_proxy_readiness"]["data_gap_counts"] == {
        "stock_target_conflict": 1
    }


def test_report_intelligence_stock_entry_suspension_blocks_labeling(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    dates = _stock_fixture_dates()
    volume = [100.0 for _ in dates]
    volume[2] = 0.0
    _write_qlib_stock_fixture(qlib_stock_dir, volume=volume)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 0
    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["stock_price_proxy_readiness"]["data_gap_counts"] == {
        "stock_entry_suspended": 1
    }


def test_report_intelligence_stock_entry_limit_locked_blocks_labeling(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_stock_entry_limit_locked_fixture(qlib_stock_dir)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 0
    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["stock_price_proxy_readiness"]["data_gap_counts"] == {
        "entry_limit_locked": 1
    }


def test_report_intelligence_stock_long_suspension_blocks_window(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    dates = _stock_fixture_dates()
    volume = [100.0 for _ in dates]
    volume[7] = 0.0
    _write_qlib_stock_fixture(qlib_stock_dir, volume=volume)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {"max_days": 120, "unit": "trading_day"},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 3
    outcome_labels = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"
    )
    assert {row["horizon_days"] for row in outcome_labels} == {20, 60, 120}
    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["stock_price_proxy_readiness"]["data_gap_counts"] == {
        "stock_long_suspension_window": 1
    }


def test_report_intelligence_stock_delisted_before_exit_blocks_labeling(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_stock_truncated_fixture(qlib_stock_dir)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {"max_days": 120, "unit": "trading_day"},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 0
    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["stock_price_proxy_readiness"]["data_gap_counts"] == {
        "stock_delisted_before_exit": 4
    }


def test_report_intelligence_stock_exit_limit_locked_blocks_window(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_stock_exit_limit_locked_fixture(qlib_stock_dir)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {"max_days": 120, "unit": "trading_day"},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 3
    outcome_labels = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"
    )
    assert {row["horizon_days"] for row in outcome_labels} == {20, 60, 120}

    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["stock_price_proxy_readiness"]["data_gap_counts"] == {
        "exit_limit_locked": 1
    }
    assert readiness["stock_price_proxy_readiness"]["labelable_window_count"] == 3


def test_report_intelligence_pit_audit_rejects_t0_stock_entry():
    audit = build_report_intelligence_pit_leakage_audit(
        run_id="RIR-PIT-STOCK-T0-TEST",
        feature_flags={
            "rollout_mode": "shadow_tooling",
            "flags": {"production_use_of_weighted_reports": False},
        },
        metadata_rows=[
            {
                "source_id": "SRC-STOCK-T0",
                "accessible_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_rows=[
            {
                "forecast_claim_id": "FC-STOCK-T0",
                "source_id": "SRC-STOCK-T0",
                "signal_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_ledger_rows=[
            {
                "forecast_claim_id": "FC-STOCK-T0",
                "as_of_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        outcome_label_rows=[
            {
                "outcome_id": "OUT-STOCK-T0",
                "forecast_claim_id": "FC-STOCK-T0",
                "entry_datetime": "2026-01-02T00:00:00+08:00",
                "exit_datetime": "2026-01-22T00:00:00+08:00",
                "pit_valid": True,
                "survivorship_safe": True,
                "label_type": "stock_price_proxy",
                "entry_lag_trading_days": 0,
                "benchmark_source": "cn_etf",
                "benchmark_alignment": "stock_calendar_index",
                "latest_calendar_date": "2026-05-31",
            }
        ],
        source_performance_profile_rows=[],
        tool_coverage_match_rows=[],
        analysis_recipe_rows=[],
        weighted_research_context_rows=[],
    )

    assert audit["accepted"] is False
    assert any("stock entry_datetime must be after signal date" in item for item in audit["blockers"])
    assert any("stock entry_lag_trading_days" in item for item in audit["blockers"])
    assert any("stock benchmark must align by date" in item for item in audit["blockers"])


def test_report_intelligence_pit_audit_rejects_stock_exit_limit_locked_label():
    audit = build_report_intelligence_pit_leakage_audit(
        run_id="RIR-PIT-STOCK-EXIT-LOCKED-TEST",
        feature_flags={
            "rollout_mode": "shadow_tooling",
            "flags": {"production_use_of_weighted_reports": False},
        },
        metadata_rows=[
            {
                "source_id": "SRC-STOCK-EXIT-LOCKED",
                "accessible_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_rows=[
            {
                "forecast_claim_id": "FC-STOCK-EXIT-LOCKED",
                "source_id": "SRC-STOCK-EXIT-LOCKED",
                "signal_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_ledger_rows=[
            {
                "forecast_claim_id": "FC-STOCK-EXIT-LOCKED",
                "as_of_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        outcome_label_rows=[
            {
                "outcome_id": "OUT-STOCK-EXIT-LOCKED",
                "forecast_claim_id": "FC-STOCK-EXIT-LOCKED",
                "entry_datetime": "2026-01-03T00:00:00+08:00",
                "exit_datetime": "2026-01-08T00:00:00+08:00",
                "pit_valid": True,
                "survivorship_safe": False,
                "survivorship_check": "survivorship_unverified_qlib_cn_data",
                "label_type": "stock_price_proxy",
                "entry_lag_trading_days": 1,
                "benchmark_source": "cn_etf",
                "benchmark_alignment": "date_key_cross_qlib_dir",
                "latest_calendar_date": "2026-05-31",
                "readiness_gaps": ["exit_limit_locked"],
            }
        ],
        source_performance_profile_rows=[],
        tool_coverage_match_rows=[],
        analysis_recipe_rows=[],
        weighted_research_context_rows=[],
    )

    assert audit["accepted"] is False
    assert any("exit_limit_locked" in item for item in audit["blockers"])


def test_report_intelligence_pit_audit_allows_shadow_stock_survivorship_unverified():
    audit = build_report_intelligence_pit_leakage_audit(
        run_id="RIR-PIT-STOCK-SURVIVORSHIP-SHADOW-TEST",
        feature_flags={
            "rollout_mode": "shadow_tooling",
            "flags": {"production_use_of_weighted_reports": False},
        },
        metadata_rows=[
            {
                "source_id": "SRC-STOCK-SURVIVORSHIP",
                "accessible_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_rows=[
            {
                "forecast_claim_id": "FC-STOCK-SURVIVORSHIP",
                "source_id": "SRC-STOCK-SURVIVORSHIP",
                "signal_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_ledger_rows=[
            {
                "forecast_claim_id": "FC-STOCK-SURVIVORSHIP",
                "as_of_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        outcome_label_rows=[
            {
                "outcome_id": "OUT-STOCK-SURVIVORSHIP",
                "forecast_claim_id": "FC-STOCK-SURVIVORSHIP",
                "entry_datetime": "2026-01-03T00:00:00+08:00",
                "exit_datetime": "2026-01-08T00:00:00+08:00",
                "pit_valid": True,
                "survivorship_safe": False,
                "survivorship_check": "survivorship_unverified_qlib_cn_data",
                "label_type": "stock_price_proxy",
                "entry_lag_trading_days": 1,
                "benchmark_source": "cn_etf",
                "benchmark_alignment": "date_key_cross_qlib_dir",
                "latest_calendar_date": "2026-05-31",
            }
        ],
        source_performance_profile_rows=[],
        tool_coverage_match_rows=[],
        analysis_recipe_rows=[],
        weighted_research_context_rows=[],
    )

    assert audit["accepted"] is True
    by_id = {row["check_id"]: row for row in audit["checks"]}
    assert by_id["RI-PIT-02"]["evidence"][
        "stock_survivorship_unverified_count"
    ] == 1


def test_report_intelligence_pit_audit_blocks_promoted_stock_survivorship_unverified():
    audit = build_report_intelligence_pit_leakage_audit(
        run_id="RIR-PIT-STOCK-SURVIVORSHIP-PROMOTED-TEST",
        feature_flags={
            "rollout_mode": "paper_trading",
            "flags": {"production_use_of_weighted_reports": False},
        },
        metadata_rows=[
            {
                "source_id": "SRC-STOCK-SURVIVORSHIP",
                "accessible_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_rows=[
            {
                "forecast_claim_id": "FC-STOCK-SURVIVORSHIP",
                "source_id": "SRC-STOCK-SURVIVORSHIP",
                "signal_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_ledger_rows=[
            {
                "forecast_claim_id": "FC-STOCK-SURVIVORSHIP",
                "as_of_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        outcome_label_rows=[
            {
                "outcome_id": "OUT-STOCK-SURVIVORSHIP",
                "forecast_claim_id": "FC-STOCK-SURVIVORSHIP",
                "entry_datetime": "2026-01-03T00:00:00+08:00",
                "exit_datetime": "2026-01-08T00:00:00+08:00",
                "pit_valid": True,
                "survivorship_safe": False,
                "survivorship_check": "survivorship_unverified_qlib_cn_data",
                "label_type": "stock_price_proxy",
                "entry_lag_trading_days": 1,
                "benchmark_source": "cn_etf",
                "benchmark_alignment": "date_key_cross_qlib_dir",
                "latest_calendar_date": "2026-05-31",
            }
        ],
        source_performance_profile_rows=[],
        tool_coverage_match_rows=[],
        analysis_recipe_rows=[],
        weighted_research_context_rows=[],
    )

    assert audit["accepted"] is False
    assert any("survivorship_unverified cannot support" in item for item in audit["blockers"])


def test_report_intelligence_cli_help_exposes_stock_qlib_dir(capsys):
    with pytest.raises(SystemExit) as exc:
        main(("report-intelligence", "--help"))

    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--qlib-stock-dir" in help_text
    assert ReportIntelligenceConfig().qlib_stock_dir == "~/.qlib/qlib_data/cn_data"


def test_report_intelligence_counts_industry_etf_proxy_as_labelable_channel(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="有色金属",
        report_type="行业研报",
        publish_date="2026-01-02",
    )
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "有色金属行业景气度改善，板块后续有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {
                            "target_type": "sector",
                            "target_id": "有色金属",
                        },
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.outcome_labeling_ready_count == 0
    assert result.outcome_labeling_blocked_count == 0
    assert result.industry_etf_proxy_outcome_label_rows == 3

    forecasts = _read_jsonl(
        tmp_path / "registry/report_intelligence/forecast_claims.jsonl"
    )
    forecast_claim_id = forecasts[0]["forecast_claim_id"]
    assert forecasts[0]["forecast_testability"] == "insufficient_mapping"
    assert forecasts[0]["extraction_quality"]["mapping_gaps"] == [
        "benchmark",
        "horizon",
    ]

    ledger = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_forecast_ledger.jsonl"
    )
    assert ledger[0]["test_status"] == "not_ready_insufficient_mapping"

    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["ready_for_outcome_labeling_count"] == 0
    assert readiness["standard_blocked_count"] == 1
    assert readiness["standard_blocked_forecast_claim_ids"] == [forecast_claim_id]
    assert readiness["proxy_label_ready_count"] == 1
    assert readiness["proxy_label_ready_forecast_claim_ids"] == [forecast_claim_id]
    assert readiness["proxy_label_only_ready_count"] == 1
    assert readiness["proxy_label_only_ready_forecast_claim_ids"] == [
        forecast_claim_id
    ]
    assert readiness["blocked_count"] == 0
    assert readiness["blocked_forecast_claim_ids"] == []
    assert readiness["blocked_reason"] == ""
    assert readiness["mapping_gap_counts"] == {"benchmark": 1, "horizon": 1}
    assert readiness["unlabelable_mapping_gap_counts"] == {}

    provenance_audit = json.loads(
        (tmp_path / "registry/report_intelligence/extraction_provenance_audit.json")
        .read_text(encoding="utf-8")
    )
    by_id = {row["check_id"]: row for row in provenance_audit["checks"]}
    assert provenance_audit["accepted"] is True
    assert by_id["RI-PROV-04"]["accepted"] is True
    assert by_id["RI-PROV-04"]["evidence"][
        "standard_blocked_forecast_count"
    ] == 1
    assert by_id["RI-PROV-04"]["evidence"]["unlabelable_forecast_count"] == 0


def test_report_intelligence_infers_explicit_horizon_from_claim_text(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="计算机",
        report_type="行业研报",
        publish_date="2026-01-02",
    )

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "计算机行业指数预期未来6个月内优于市场指数5%以上",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {
                            "target_type": "sector",
                            "target_id": "计算机行业",
                        },
                        "benchmark": {
                            "benchmark_type": "market_index",
                            "benchmark_id": "市场基准指数",
                        },
                        "direction": "positive",
                        "horizon": {},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.outcome_labeling_ready_count == 1
    assert result.outcome_labeling_blocked_count == 0
    forecasts = _read_jsonl(tmp_path / "registry/report_intelligence/forecast_claims.jsonl")
    assert forecasts[0]["forecast_testability"] == "testable"
    assert forecasts[0]["horizon"]["max_days"] == 183
    assert forecasts[0]["horizon"]["source"] == "explicit_claim_text"
    assert forecasts[0]["extraction_quality"]["horizon_inferred_from_claim_text"] is True
    assert "mapping_gaps" not in forecasts[0]["extraction_quality"]

    ledger = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_forecast_ledger.jsonl"
    )
    assert ledger[0]["test_status"] == "ready_for_outcome_labeling"
    assert ledger[0]["forecast_family_id"].startswith("FF-")


def test_report_intelligence_derived_refresh_backfills_explicit_horizon(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="计算机",
        report_type="行业研报",
        publish_date="2026-01-02",
    )

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "计算机行业指数预期未来6个月内优于市场指数5%以上",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {
                            "target_type": "sector",
                            "target_id": "计算机行业",
                        },
                        "benchmark": {
                            "benchmark_type": "market_index",
                            "benchmark_id": "市场基准指数",
                        },
                        "direction": "positive",
                        "horizon": {"max_days": 183, "unit": "calendar_day"},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )
    forecast_path = tmp_path / "registry/report_intelligence/forecast_claims.jsonl"
    forecasts = _read_jsonl(forecast_path)
    forecasts[0]["horizon"] = {}
    forecasts[0]["forecast_testability"] = "insufficient_mapping"
    forecasts[0]["extraction_quality"]["mapping_gaps"] = ["horizon"]
    _write_jsonl(forecast_path, forecasts)

    result = run_report_intelligence_derived_refresh(
        ReportIntelligenceConfig(root=tmp_path, refresh_derived_only=True)
    )

    assert result.outcome_labeling_ready_count == 1
    assert "patch_v1_5_coverage_report" in result.outputs
    refreshed = _read_jsonl(forecast_path)
    assert refreshed[0]["forecast_testability"] == "testable"
    assert refreshed[0]["horizon"]["max_days"] == 183
    assert "mapping_gaps" not in refreshed[0]["extraction_quality"]
    patch_coverage = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/patch_v1_5_coverage_report.json"
        ).read_text(encoding="utf-8")
    )
    assert patch_coverage["phase_count"] == 8


def test_report_intelligence_keeps_long_window_industry_etf_hits(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="有色金属",
        report_type="行业研报",
        publish_date="2026-01-02",
    )
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_mixed_window_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "有色金属行业长期景气向上，板块中长期看多。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {"target_type": "sector", "target_id": "有色金属"},
                        "benchmark": {
                            "benchmark_type": "broad_index",
                            "benchmark_id": "CSI300",
                        },
                        "direction": "positive",
                        "horizon": {
                            "min_days": 20,
                            "max_days": 120,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.industry_etf_proxy_outcome_label_rows == 3
    outcome_labels = sorted(
        _read_jsonl(tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"),
        key=lambda row: row["horizon_days"],
    )
    assert [row["window_role"] for row in outcome_labels] == [
        "short",
        "medium",
        "long",
    ]
    assert [row["effective_n_weight"] for row in outcome_labels] == [0.25, 0.35, 0.4]
    assert outcome_labels[0]["directional_hit"] is False
    assert outcome_labels[-1]["directional_hit"] is True
    assert outcome_labels[0]["directional_after_cost_return"] < 0
    assert outcome_labels[-1]["directional_after_cost_return"] > 0
    assert {row["performance_value_basis"] for row in outcome_labels} == {
        "directional_after_cost_return"
    }
    assert {row["outcome_label_source"] for row in outcome_labels} == {
        "pit_industry_etf_price_window"
    }
    assert {row["llm_outcome_labeling_allowed"] for row in outcome_labels} == {False}

    summary = outcome_labels[0]["temporal_validation_summary"]
    assert summary["temporal_validation_bucket"] == "short_miss_long_hit"
    assert summary["miss_window_days"] == [20]
    assert summary["hit_window_days"] == [60, 120]
    assert summary["short_window_directional_hit"] is False
    assert summary["long_window_directional_hit"] is True
    assert summary["long_window_hit_retained"] is True
    assert (
        summary["window_evidence_policy"]
        == "do_not_collapse_multi_window_outcome_to_single_label"
    )

    statistical_audit = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/statistical_robustness_audit.json"
        ).read_text(encoding="utf-8")
    )
    assert statistical_audit["accepted"] is True
    assert statistical_audit["checks"][1]["evidence"][
        "industry_etf_proxy_label_rows"
    ] == 3
    assert (
        statistical_audit["checks"][1]["evidence"]["outcome_label_source"]
        == "pit_industry_etf_price_window"
    )
    assert (
        statistical_audit["checks"][1]["evidence"]["llm_outcome_labeling_allowed"]
        is False
    )
    assert statistical_audit["checks"][3]["evidence"][
        "complete_industry_etf_window_set_count"
    ] == 1
    assert statistical_audit["checks"][6]["evidence"][
        "short_miss_long_hit_window_set_count"
    ] == 1


def test_report_intelligence_scores_bearish_industry_reports_with_etf_declines(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="有色金属",
        report_type="行业研报",
        publish_date="2026-01-02",
    )
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_bearish_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "有色金属行业需求承压，板块中期看空。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {"target_type": "sector", "target_id": "有色金属"},
                        "benchmark": {
                            "benchmark_type": "broad_index",
                            "benchmark_id": "CSI300",
                        },
                        "direction": "negative",
                        "horizon": {
                            "min_days": 20,
                            "max_days": 120,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.industry_etf_proxy_outcome_label_rows == 3
    outcome_labels = sorted(
        _read_jsonl(tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"),
        key=lambda row: row["horizon_days"],
    )
    assert {row["direction_evaluated"] for row in outcome_labels} == {"negative"}
    assert all(row["proxy_return"] < 0 for row in outcome_labels)
    assert all(row["directional_proxy_return"] > 0 for row in outcome_labels)
    assert all(row["directional_hit"] is True for row in outcome_labels)
    assert all(row["relative_directional_hit"] is True for row in outcome_labels)
    assert {row["outcome_label_source"] for row in outcome_labels} == {
        "pit_industry_etf_price_window"
    }
    assert {row["llm_outcome_labeling_allowed"] for row in outcome_labels} == {False}
    assert outcome_labels[0]["temporal_validation_summary"][
        "temporal_validation_bucket"
    ] == "consistent_hit"


def test_report_intelligence_refresh_derived_only_rebuilds_window_labels(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="工业金属",
        report_type="行业研报",
        publish_date="2026-01-02",
    )
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "工业金属行业景气向上，后续走势看多。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {"target_type": "sector", "target_id": "工业金属"},
                        "benchmark": {
                            "benchmark_type": "broad_index",
                            "benchmark_id": "CSI300",
                        },
                        "direction": "positive",
                        "horizon": {
                            "min_days": 20,
                            "max_days": 120,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )
    labels_path = tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"
    labels_path.write_text("", encoding="utf-8")

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            qlib_etf_dir=qlib_etf_dir,
            refresh_derived_only=True,
        )
    )

    assert result.run_id.startswith("RIR-DERIVED-")
    assert result.selected_reports == 1
    assert result.llm_processed_reports == 1
    assert result.outcome_label_rows == 3
    assert result.industry_etf_proxy_outcome_label_rows == 3
    labels = _read_jsonl(labels_path)
    assert {row["horizon_days"] for row in labels} == {20, 60, 120}


def test_report_intelligence_performance_profiles_use_shrunk_outcomes():
    metadata_rows = [
        {
            "source_id": "SRC-1",
            "institution_id": "INST-1",
            "institution": "Broker A",
            "author_ids": ["AUTH-1"],
            "author": "Analyst A",
            "market": "CN_A_SHARE",
            "sector": "工业金属",
            "accessible_datetime": "2026-01-02T00:00:00+08:00",
        }
    ]
    forecast_rows = [
        {
            "claim_id": "CLAIM-1",
            "forecast_claim_id": "FC-1",
            "source_id": "SRC-1",
            "source_span_ids": ["SRC-1:original_markdown:chunk-001"],
            "forecast_testability": "testable",
            "forecast_type": "industry_outlook",
            "direction": "positive",
            "metric_proxy_mapping": ["inventory_to_sales"],
            "horizon": {"min_days": 20, "max_days": 60, "unit": "trading_day"},
            "failure_modes": [{"text": "库存重新累积"}],
        }
    ]
    outcome_rows = [
        {
            "forecast_claim_id": "FC-1",
            "entry_datetime": "2026-01-03",
            "exit_datetime": "2026-01-31",
            "directional_hit": True,
            "after_cost_alpha": 0.02,
            "effective_n_weight": 1.0,
            "pit_valid": True,
            "survivorship_safe": True,
        },
        {
            "forecast_claim_id": "FC-1",
            "entry_datetime": "2026-01-03",
            "exit_datetime": "2026-02-10",
            "directional_hit": True,
            "after_cost_alpha": 0.01,
            "effective_n_weight": 1.0,
            "pit_valid": True,
            "survivorship_safe": True,
        },
        {
            "forecast_claim_id": "FC-1",
            "entry_datetime": "2026-01-03",
            "exit_datetime": "2026-02-20",
            "directional_hit": False,
            "after_cost_alpha": -0.005,
            "effective_n_weight": 1.0,
            "pit_valid": True,
            "survivorship_safe": True,
        },
        {
            "forecast_claim_id": "FC-1",
            "entry_datetime": "2026-01-03",
            "exit_datetime": "2026-03-02",
            "directional_hit": True,
            "after_cost_alpha": 0.015,
            "effective_n_weight": 1.0,
            "pit_valid": True,
            "survivorship_safe": True,
        },
    ]

    source_profiles = build_source_performance_profiles(
        metadata_rows,
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_rows,
    )
    institution = next(row for row in source_profiles if row["entity_type"] == "institution")
    author = next(row for row in source_profiles if row["entity_type"] == "author")
    assert institution["n_nominal"] == 4
    assert institution["n_effective"] == 4.0
    assert institution["hit_rate"] == 0.75
    assert institution["mean_after_cost_alpha"] == 0.01
    assert institution["shrunk_performance_bucket"] == "positive_low_effective_n"
    assert institution["weight_multiplier"] == 1.03
    assert institution["insufficient_data"] is False
    assert institution["as_of_datetime"] == "2026-03-02T00:00:00+00:00"
    assert "performance_as_of_after_outcome_exit" in institution["methodology_notes"]
    assert author["shrunk_performance_bucket"] == institution["shrunk_performance_bucket"]

    viewpoint_profiles = build_viewpoint_performance_profiles(
        forecast_rows,
        outcome_label_rows=outcome_rows,
    )
    assert len(viewpoint_profiles) == 1
    viewpoint = viewpoint_profiles[0]
    assert viewpoint["mechanism_chain"] == ["inventory_to_sales"]
    assert viewpoint["n_effective"] == 4.0
    assert viewpoint["viewpoint_weight_multiplier"] == 1.03
    assert viewpoint["known_failure_modes"] == ["库存重新累积"]
    assert viewpoint["last_revalidated_at"] == "2026-03-02T00:00:00+00:00"
    assert "research_prior_only_not_signal" in viewpoint["methodology_notes"]

    contexts = build_weighted_research_contexts(
        forecast_rows=forecast_rows,
        footprint_rows=[],
        analysis_recipe_rows=[],
        tool_gap_rows=[],
        metadata_rows=metadata_rows,
        source_performance_profile_rows=source_profiles,
        viewpoint_performance_profile_rows=viewpoint_profiles,
    )
    weighted_claim = contexts[0]["retrieved_claims"][0]
    assert weighted_claim["source_weight_multiplier"] == 1.03
    assert weighted_claim["viewpoint_weight_multiplier"] == 1.03
    assert weighted_claim["combined_research_prior_weight"] == 1.0609
    assert weighted_claim["performance_context_match"] == "source_and_viewpoint_profile_match"
    assert weighted_claim["current_data_required"] is True
    assert contexts[0]["research_only"] is True
    assert contexts[0]["actionability"] == "no_trade_without_current_data_confirmation"


def test_report_intelligence_does_not_fallback_to_abstract_when_markdown_missing(
    tmp_path: Path,
):
    _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        url="",
    )

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            skip_download=True,
            skip_convert=True,
        ),
        llm_extractor=_fake_llm,
    )

    assert result.blocker_count > 0
    assert result.forecast_claim_rows == 0
    assert any("original_markdown_missing" in blocker for blocker in result.blockers)


def test_report_intelligence_converts_text_source_without_mineru(tmp_path: Path):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        url="https://example.invalid/report.txt",
    )

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,), skip_llm=True),
        downloader=_fake_text_downloader,
    )

    assert result.blocker_count == 0
    assert result.pdf_ready_count == 1
    assert result.markdown_ready_count == 1
    metadata = _read_jsonl(tmp_path / "registry/report_intelligence/report_metadata.jsonl")
    markdown = metadata[0]["markdown"]
    assert markdown["status"] == "converted_text_source"
    markdown_path = tmp_path / markdown["path"]
    assert "电子材料平台迎来结构性拐点" in markdown_path.read_text(encoding="utf-8")


def test_report_intelligence_demotes_unmapped_forecasts_and_filters_agent_ids(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "行业景气度将继续向上。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "sector_outlook",
                        "direction": "positive",
                    }
                ],
                "analytical_footprints": [
                    {
                        "topic": "invalid_agent_candidate_filter",
                        "indicator_mentions": [],
                        "analysis_patterns": [],
                        "target_agent_candidates": ["Anthropic", "macro.central_bank"],
                    }
                ],
                "metric_candidates": [
                    {
                        "canonical_name": "private_metric",
                        "target_agents": ["SpaceX", "macro.central_bank"],
                    }
                ],
                "method_patterns": [
                    {
                        "name": "private_method",
                        "target_agents": ["英伟达", "macro.central_bank"],
                    }
                ],
                "tool_gaps": [
                    {
                        "gap_type": "missing_metric",
                        "metric_name": "private_metric",
                        "target_agents": ["行业分析师", "macro.central_bank"],
                    }
                ],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.forecast_claim_rows == 1
    forecasts = _read_jsonl(tmp_path / "registry/report_intelligence/forecast_claims.jsonl")
    assert forecasts[0]["forecast_testability"] == "insufficient_mapping"
    assert forecasts[0]["extraction_quality"]["mapping_gaps"] == [
        "target",
        "benchmark",
        "horizon",
    ]

    ledger = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_forecast_ledger.jsonl"
    )
    assert ledger[0]["test_status"] == "not_ready_insufficient_mapping"

    footprints = _read_jsonl(
        tmp_path / "registry/report_intelligence/analytical_footprints.jsonl"
    )
    assert footprints[0]["target_agent_candidates"] == ["macro.central_bank"]
    assert footprints[0]["target_entity_candidates"] == ["Anthropic"]

    metrics = _read_jsonl(tmp_path / "registry/report_intelligence/metric_candidates.jsonl")
    assert metrics[0]["target_agents"] == ["macro.central_bank"]

    tool_gaps = _read_jsonl(tmp_path / "registry/report_intelligence/tool_gaps.jsonl")
    assert tool_gaps[0]["target_agents"] == ["macro.central_bank"]

    weighted = _read_jsonl(
        tmp_path / "registry/report_intelligence/weighted_research_contexts.jsonl"
    )
    assert [row["agent_id"] for row in weighted] == ["macro.central_bank"]


def test_report_intelligence_normalizes_unsupported_forecast_direction(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "利润增速有升有降，方向混合。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "historical_performance",
                        "target": {
                            "target_type": "stock",
                            "target_id": "000028.SZ",
                        },
                        "direction": "mixed",
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    forecasts = _read_jsonl(tmp_path / "registry/report_intelligence/forecast_claims.jsonl")
    assert forecasts[0]["direction"] == "ambiguous"
    assert forecasts[0]["forecast_testability"] == "insufficient_mapping"
    assert forecasts[0]["extraction_quality"]["mapping_gaps"] == [
        "benchmark",
        "direction",
        "horizon",
    ]


def test_apply_analytical_footprint_review_import_updates_summary(tmp_path: Path):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )
    template_path = (
        tmp_path
        / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    )
    rows = _read_jsonl(template_path)
    reviewed_rows = []
    for row in rows:
        reviewed = dict(row)
        reviewed.update(
            {
                "footprint_correct": True,
                "source_span_supports_footprint": True,
                "metric_mapping_correct": True,
                "inferred_steps_tagged_correctly": True,
                "unknowns_used_when_uncertain": True,
                "no_proprietary_text_leakage": True,
                "manual_error_tags": [],
                "reviewer": "footprint-reviewer",
                "review_date": "2026-06-07",
                "review_notes": "fixture approval",
            }
        )
        reviewed_rows.append(reviewed)
    import_path = tmp_path / "registry/report_intelligence/footprint_reviewed.jsonl"
    _write_jsonl(import_path, reviewed_rows)

    dry_run = apply_analytical_footprint_review_import(
        tmp_path,
        import_path,
        dry_run=True,
    )
    report = apply_analytical_footprint_review_import(tmp_path, import_path)

    assert dry_run.accepted
    assert dry_run.applied_rows == 0
    assert report.accepted
    assert report.applied_rows == len(reviewed_rows)
    summary = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/analytical_footprint_review_summary.json"
        ).read_text(encoding="utf-8")
    )
    assert summary["accepted"] is True
    assert summary["review_complete"] is True
    assert summary["quality_gate_passed"] is True
    assert summary["quality_gate_blockers"] == []
    assert summary["pending_rows"] == 0
    assert summary["complete_rows"] == len(reviewed_rows)


def test_analytical_footprint_review_summary_requires_quality_thresholds(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )
    rows = _read_jsonl(
        tmp_path
        / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    )
    reviewed_rows = []
    for row in rows:
        reviewed = dict(row)
        reviewed.update(
            {
                "footprint_correct": True,
                "source_span_supports_footprint": True,
                "metric_mapping_correct": False,
                "inferred_steps_tagged_correctly": True,
                "unknowns_used_when_uncertain": True,
                "no_proprietary_text_leakage": True,
                "manual_error_tags": ["metric_mapping_error"],
                "reviewer": "footprint-reviewer",
                "review_date": "2026-06-07",
                "review_notes": "fixture low quality",
            }
        )
        reviewed_rows.append(reviewed)
    import_path = tmp_path / "registry/report_intelligence/footprint_reviewed.jsonl"
    _write_jsonl(import_path, reviewed_rows)

    report = apply_analytical_footprint_review_import(tmp_path, import_path)

    assert report.accepted
    summary = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/analytical_footprint_review_summary.json"
        ).read_text(encoding="utf-8")
    )
    assert summary["review_complete"] is True
    assert summary["accepted"] is False
    assert summary["quality_gate_passed"] is False
    assert any(
        "metric_mapping_accuracy" in blocker
        for blocker in summary["quality_gate_blockers"]
    )


def test_apply_analytical_footprint_review_import_rejects_stale_or_leaky_rows(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )
    row = _read_jsonl(
        tmp_path
        / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    )[0]
    row.update(
        {
            "footprint_correct": True,
            "source_span_supports_footprint": True,
            "metric_mapping_correct": True,
            "inferred_steps_tagged_correctly": True,
            "unknowns_used_when_uncertain": True,
            "no_proprietary_text_leakage": False,
            "manual_error_tags": ["proprietary_text_leakage"],
            "reviewer": "footprint-reviewer",
            "review_date": "2026-06-07",
            "review_notes": "fixture rejection",
            "source_text": "full source text must not enter review import",
            "target_row_hash": "sha256:stale",
        }
    )
    import_path = tmp_path / "registry/report_intelligence/footprint_reviewed.jsonl"
    _write_jsonl(import_path, [row])

    report = apply_analytical_footprint_review_import(tmp_path, import_path)
    reasons = " ".join(
        reason for invalid in report.invalid_rows for reason in invalid.reasons
    )

    assert not report.accepted
    assert "target_row_hash does not match target review row" in reasons
    assert "source_text forbidden in analytical footprint review import" in reasons
    assert report.applied_rows == 0


def test_report_intelligence_structures_string_indicator_mentions(tmp_path: Path):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [],
                "analytical_footprints": [
                    {
                        "topic": "string_indicator_mention",
                        "indicator_mentions": ["DR007与政策利率利差"],
                        "analysis_patterns": [],
                        "target_agent_candidates": ["macro.central_bank"],
                    }
                ],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    footprints = _read_jsonl(
        tmp_path / "registry/report_intelligence/analytical_footprints.jsonl"
    )
    mention = footprints[0]["indicator_mentions"][0]
    assert mention == {
        "canonical_metric_candidate": "dr007_policy_rate_spread",
        "data_source_mentioned": "interbank_repo_rate_and_policy_rate",
        "frequency": "daily",
        "indicator_text": "DR007与政策利率利差",
        "lookback_window": {},
        "role_in_argument": "funding_stress_proxy",
        "source_grounded": True,
        "transformation": "spread",
    }


def test_report_intelligence_bounds_stored_claim_text(tmp_path: Path):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    long_claim_text = (
        "公开市场净投放连续改善并且DR007相对政策利率回落时，"
        "高beta风格相对沪深300在未来二十个交易日可能显著占优，"
        "但若资金面重新收紧则该判断需要下调。"
    )

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": long_claim_text,
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "macro_regime_to_style_relative_direction",
                        "target": {
                            "target_type": "style_index",
                            "target_id": "CN_A_SHARE_HIGH_BETA",
                        },
                        "benchmark": {
                            "benchmark_type": "broad_index",
                            "benchmark_id": "CSI300",
                        },
                        "direction": "positive",
                        "horizon": {
                            "min_days": 5,
                            "max_days": 20,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    forecasts = _read_jsonl(tmp_path / "registry/report_intelligence/forecast_claims.jsonl")
    assert len(forecasts[0]["claim_text"]) <= 72
    assert forecasts[0]["claim_text"].endswith("...")
    assert forecasts[0]["extraction_quality"]["claim_text_truncated_for_redaction"] is True
    assert long_claim_text not in forecasts[0]["claim_text"]


def test_report_intelligence_reports_missing_mineru_command(tmp_path: Path):
    _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            skip_llm=True,
            mineru_command="definitely-not-a-mineru-command",
        ),
        downloader=_fake_downloader,
    )

    assert result.blocker_count == 1
    assert "mineru_command_not_found" in result.blockers[0]
    status = _read_jsonl(tmp_path / "registry/report_intelligence/processing_status.jsonl")
    assert status[0]["markdown_status"] == "blocked"


def test_report_intelligence_redacts_runtime_log_fields(tmp_path: Path):
    _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    api_key = "sk-" + "abc123456789012345"
    provider_key = "tp-" + "abc123456789012345"
    token_name = "TUSHARE_" + "TOKEN"
    token_value = "abcdef123456"

    def converter(pdf: Path, output_dir: Path, markdown: Path, overwrite: bool):
        return {
            "status": "blocked",
            "blocker": "mineru_failed",
            "command": f"mineru -p {tmp_path}/secret.pdf --key={api_key}",
            "stderr_tail": f"failed in {tmp_path}; {token_name}={token_value}",
            "stdout_tail": f"provider key:{provider_key}",
        }

    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, skip_llm=True),
        downloader=_fake_downloader,
        converter=converter,
    )

    metadata = _read_jsonl(tmp_path / "registry/report_intelligence/report_metadata.jsonl")
    status = _read_jsonl(tmp_path / "registry/report_intelligence/processing_status.jsonl")
    markdown = metadata[0]["markdown"]
    assert str(tmp_path) not in markdown["command"]
    assert str(tmp_path) not in markdown["stderr_tail"]
    assert api_key not in markdown["command"]
    assert token_value not in markdown["stderr_tail"]
    assert provider_key not in markdown["stdout_tail"]
    assert str(tmp_path) not in status[0]["markdown_stderr_tail"]


def test_report_intelligence_cli_can_write_status_without_network(
    tmp_path: Path,
    capsys,
):
    _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")

    code = main(
        (
            "report-intelligence",
            "--root",
            str(tmp_path),
            "--limit",
            "1",
            "--skip-download",
            "--skip-convert",
            "--skip-llm",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["selected_reports"] == 1
    assert output["blocker_count"] == 0
    assert (tmp_path / "registry/report_intelligence/extraction_report.json").exists()


def test_report_intelligence_tool_coverage_classifier():
    assert classify_tool_coverage("pboc_net_injection_7d")["coverage_status"] == "exact_match"
    assert classify_tool_coverage("dr007_policy_rate_spread")["coverage_status"] == "partial_match"
    assert classify_tool_coverage("missing_private_metric")["coverage_status"] == "missing"


def test_report_intelligence_defaults_to_hybrid_mineru_backend():
    config = ReportIntelligenceConfig()

    assert config.mineru_backend == "hybrid-auto-engine"
    assert "{backend}" in DEFAULT_MINERU_ARGS_TEMPLATE


def test_mineru_batch_conversion_uses_directory_input(tmp_path: Path):
    fake_mineru = tmp_path / "fake-mineru"
    fake_mineru.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import sys",
                "from pathlib import Path",
                "args = sys.argv[1:]",
                "input_dir = Path(args[args.index('-p') + 1])",
                "output_dir = Path(args[args.index('-o') + 1])",
                "backend = args[args.index('-b') + 1]",
                "assert input_dir.is_dir()",
                "for pdf in sorted(input_dir.glob('*.pdf')):",
                "    target = output_dir / pdf.stem / backend.replace('-', '_')",
                "    target.mkdir(parents=True, exist_ok=True)",
                "    (target / f'{pdf.stem}.md').write_text(",
                "        f'# {pdf.stem}\\nbackend={backend}\\n',",
                "        encoding='utf-8',",
                "    )",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_mineru.chmod(0o755)
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    pdf_a = pdf_dir / "SRC-A.pdf"
    pdf_b = pdf_dir / "SRC-B.pdf"
    pdf_a.write_bytes(b"%PDF A")
    pdf_b.write_bytes(b"%PDF B")

    results = convert_pdfs_with_mineru_batch(
        (
            MineruBatchConversionTask(
                source_id="SRC-A",
                pdf_path=pdf_a,
                markdown_path=tmp_path / "markdown" / "SRC-A.md",
            ),
            MineruBatchConversionTask(
                source_id="SRC-B",
                pdf_path=pdf_b,
                markdown_path=tmp_path / "markdown" / "SRC-B.md",
            ),
        ),
        tmp_path / "mineru_batch",
        overwrite=False,
        command=str(fake_mineru),
        backend="vlm-auto-engine",
        batch_size=2,
        max_batch_bytes=8,
    )

    assert results["SRC-A"]["status"] == "converted"
    assert results["SRC-B"]["status"] == "converted"
    assert results["SRC-A"]["backend"] == "vlm-auto-engine"
    assert (tmp_path / "mineru_batch" / "input-002").exists()
    assert (tmp_path / "markdown" / "SRC-A.md").read_text(encoding="utf-8").startswith("# SRC-A")
