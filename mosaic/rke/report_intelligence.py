"""Local-first report intelligence pipeline for RKE.

This module materializes Tushare research-report PDFs, converts them to
Markdown through MinerU, and extracts forecast claims plus analytical
footprints with a local OpenAI-compatible vLLM endpoint. The old Phase -1
abstract corpus remains intact; this pipeline makes original report text the
auditable input for the v1.5 Report Intelligence Loop.
"""

from __future__ import annotations

import json
import os
import re
import signal
import shlex
import shutil
import struct
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Sequence

from .manual_review_import import manual_review_forbidden_field_paths
from .phase_minus1 import load_jsonl_with_errors


TUSHARE_REPORT_SOURCE_PATH = "registry/sources/tushare_research_reports.jsonl"
REPORT_INTELLIGENCE_REGISTRY_DIR = "registry/report_intelligence"
REPORT_INTELLIGENCE_CACHE_DIR = ".mosaic/rke/report_intelligence"
ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH = (
    "registry/report_intelligence/analytical_footprint_review_template.jsonl"
)
ANALYTICAL_FOOTPRINT_REVIEW_SUMMARY_PATH = (
    "registry/report_intelligence/analytical_footprint_review_summary.json"
)
ANALYTICAL_FOOTPRINT_REVIEW_IMPORT_REPORT_PATH = (
    "registry/report_intelligence/analytical_footprint_review_import_report.json"
)
ANALYTICAL_FOOTPRINT_ERROR_TAXONOMY_PATH = (
    "registry/report_intelligence/analytical_footprint_error_taxonomy.json"
)
REPORT_INTELLIGENCE_RUNTIME_SAFETY_AUDIT_PATH = (
    "registry/report_intelligence/runtime_safety_audit.json"
)
REPORT_INTELLIGENCE_PIT_LEAKAGE_AUDIT_PATH = (
    "registry/report_intelligence/pit_leakage_audit.json"
)
REPORT_INTELLIGENCE_EXTRACTION_PROVENANCE_AUDIT_PATH = (
    "registry/report_intelligence/extraction_provenance_audit.json"
)
REPORT_INTELLIGENCE_STATISTICAL_ROBUSTNESS_AUDIT_PATH = (
    "registry/report_intelligence/statistical_robustness_audit.json"
)
REPORT_INTELLIGENCE_TOOL_FEASIBILITY_AUDIT_PATH = (
    "registry/report_intelligence/tool_feasibility_audit.json"
)
REPORT_INTELLIGENCE_RECIPE_VALIDATION_AUDIT_PATH = (
    "registry/report_intelligence/recipe_validation_audit.json"
)
REPORT_INTELLIGENCE_PATCH_V1_5_COVERAGE_REPORT_PATH = (
    "registry/report_intelligence/patch_v1_5_coverage_report.json"
)
REPORT_INTELLIGENCE_MARKDOWN_COVERAGE_SUMMARY_PATH = (
    "registry/report_intelligence/markdown_coverage_summary.json"
)
REPORT_INTELLIGENCE_INDUSTRY_ETF_PROXY_MAP_PATH = (
    "registry/report_intelligence/industry_etf_proxy_map.jsonl"
)
REPORT_INTELLIGENCE_INDUSTRY_ETF_PROXY_PIT_AVAILABILITY_PATH = (
    "registry/report_intelligence/industry_etf_proxy_pit_availability.json"
)
REPORT_INTELLIGENCE_RECIPE_PAPER_TRADING_RUNS_PATH = (
    "registry/report_intelligence/recipe_paper_trading_runs.jsonl"
)
REPORT_INTELLIGENCE_RECIPE_PAPER_TRADING_SUMMARY_PATH = (
    "registry/report_intelligence/recipe_paper_trading_summary.json"
)
REPORT_INTELLIGENCE_CONFIDENCE_IMPACT_OBSERVATIONS_PATH = (
    "registry/report_intelligence/confidence_impact_observations.jsonl"
)
REPORT_INTELLIGENCE_CONFIDENCE_IMPACT_MONITOR_PATH = (
    "registry/report_intelligence/confidence_impact_monitor.json"
)
REPORT_INTELLIGENCE_PROMPT_MUTATION_CANDIDATES_PATH = (
    "registry/report_intelligence/prompt_mutation_candidates.jsonl"
)
REPORT_INTELLIGENCE_EVOLUTION_READINESS_GATE_PATH = (
    "registry/report_intelligence/evolution_readiness_gate.json"
)
REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS = frozenset(
    {
        ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
        "registry/report_intelligence/analytical_footprint_reviewed.jsonl",
        "registry/report_intelligence/analytical_footprints.jsonl",
        "registry/report_intelligence/forecast_claims.jsonl",
        "registry/report_intelligence/processing_status.jsonl",
        "registry/report_intelligence/report_metadata.jsonl",
        "registry/report_intelligence/report_outcome_labels.jsonl",
        "registry/report_intelligence/weighted_research_contexts.jsonl",
    }
)
REPORT_INTELLIGENCE_REQUIRED_PRIVATE_DERIVED_INPUT_PATHS = frozenset(
    {
        "registry/report_intelligence/analytical_footprints.jsonl",
        "registry/report_intelligence/forecast_claims.jsonl",
        "registry/report_intelligence/report_metadata.jsonl",
    }
)
REPORT_INTELLIGENCE_PUBLIC_DERIVED_OUTPUT_PATHS = frozenset(
    {
        ANALYTICAL_FOOTPRINT_ERROR_TAXONOMY_PATH,
        ANALYTICAL_FOOTPRINT_REVIEW_IMPORT_REPORT_PATH,
        ANALYTICAL_FOOTPRINT_REVIEW_SUMMARY_PATH,
        REPORT_INTELLIGENCE_EXTRACTION_PROVENANCE_AUDIT_PATH,
        REPORT_INTELLIGENCE_PATCH_V1_5_COVERAGE_REPORT_PATH,
        REPORT_INTELLIGENCE_PIT_LEAKAGE_AUDIT_PATH,
        REPORT_INTELLIGENCE_RECIPE_VALIDATION_AUDIT_PATH,
        REPORT_INTELLIGENCE_RUNTIME_SAFETY_AUDIT_PATH,
        REPORT_INTELLIGENCE_STATISTICAL_ROBUSTNESS_AUDIT_PATH,
        REPORT_INTELLIGENCE_TOOL_FEASIBILITY_AUDIT_PATH,
        "registry/report_intelligence/analysis_recipes.jsonl",
        "registry/report_intelligence/data_acquisition_proposals.jsonl",
        "registry/report_intelligence/extraction_report.json",
        "registry/report_intelligence/feature_flags.json",
        REPORT_INTELLIGENCE_INDUSTRY_ETF_PROXY_MAP_PATH,
        REPORT_INTELLIGENCE_INDUSTRY_ETF_PROXY_PIT_AVAILABILITY_PATH,
        REPORT_INTELLIGENCE_MARKDOWN_COVERAGE_SUMMARY_PATH,
        "registry/report_intelligence/method_patterns.jsonl",
        "registry/report_intelligence/method_performance_profiles.jsonl",
        "registry/report_intelligence/metric_candidates.jsonl",
        "registry/report_intelligence/monitoring_report.json",
        "registry/report_intelligence/outcome_labeling_readiness.json",
        REPORT_INTELLIGENCE_CONFIDENCE_IMPACT_MONITOR_PATH,
        REPORT_INTELLIGENCE_CONFIDENCE_IMPACT_OBSERVATIONS_PATH,
        REPORT_INTELLIGENCE_EVOLUTION_READINESS_GATE_PATH,
        REPORT_INTELLIGENCE_PROMPT_MUTATION_CANDIDATES_PATH,
        REPORT_INTELLIGENCE_RECIPE_PAPER_TRADING_RUNS_PATH,
        REPORT_INTELLIGENCE_RECIPE_PAPER_TRADING_SUMMARY_PATH,
        "registry/report_intelligence/report_forecast_ledger.jsonl",
        "registry/report_intelligence/runtime_tool_gap_observations.jsonl",
        "registry/report_intelligence/source_performance_profiles.jsonl",
        "registry/report_intelligence/tool_coverage_matches.jsonl",
        "registry/report_intelligence/tool_design_proposals.jsonl",
        "registry/report_intelligence/tool_gaps.jsonl",
        "registry/report_intelligence/viewpoint_performance_profiles.jsonl",
    }
)
DEFAULT_VLLM_BASE_URL = "http://127.0.0.1:8020/v1"
DEFAULT_Q_LIB_ETF_PATH = "~/.qlib/qlib_data/cn_etf"
DEFAULT_Q_LIB_STOCK_PATH = "~/.qlib/qlib_data/cn_data"
DEFAULT_MINERU_BACKEND = "hybrid-auto-engine"
DEFAULT_MINERU_ARGS_TEMPLATE = "-p {pdf} -o {output_dir} -b {backend} -m auto"
MINERU_BACKENDS = (
    "hybrid-auto-engine",
    "vlm-auto-engine",
    "pipeline",
    "vlm-http-client",
    "hybrid-http-client",
)

REPORT_INTELLIGENCE_FEATURE_FLAGS: Mapping[str, bool] = {
    "report_weighting_enabled": True,
    "analytical_footprint_enabled": True,
    "weighted_research_retriever_enabled": True,
    "method_pattern_registry_enabled": True,
    "tool_design_loop_enabled": True,
    "shadow_tool_runtime_enabled": True,
    "production_use_of_weighted_reports": False,
}
REPORT_INTELLIGENCE_ROLLOUT_MODE = "shadow_tooling"
REPORT_INTELLIGENCE_ROLLOUT_MODES = (
    "off",
    "extraction_only",
    "shadow_retrieval",
    "shadow_tooling",
    "paper_trading",
    "limited_production",
    "production",
)
REPORT_INTELLIGENCE_SAFE_ACTIONABILITY = "no_trade_without_current_data_confirmation"
REPORT_INTELLIGENCE_MAX_SAFE_ROLLOUT_MODE = "shadow_tooling"
REPORT_INTELLIGENCE_FORBIDDEN_SHADOW_OUTPUT_FIELDS = (
    "sector_score",
    "sizing",
    "position_size",
    "portfolio_weight",
    "portfolio_action",
    "trade_recommendation",
    "executable_order",
)
REPORT_INTELLIGENCE_TOOL_COVERAGE_STATUSES = (
    "exact_match",
    "partial_match",
    "proxy_available",
    "missing",
    "no_pit_history",
    "license_blocked",
    "engineering_blocked",
    "retired",
)
REPORT_INTELLIGENCE_TOOL_GAP_PRIORITY_BUCKETS = (
    "blocked",
    "low",
    "medium",
    "high",
    "urgent",
)
REPORT_INTELLIGENCE_COVERAGE_DETAIL_FIELDS = (
    "raw_source_match",
    "frequency_match",
    "pit_available",
    "lookback_supported",
    "unit_supported",
    "license_ok",
)
REPORT_INTELLIGENCE_RECIPE_RUNTIME_MODES = (
    "shadow_only",
    "validation_candidate",
    "paper_trading",
    "limited_production",
    "production",
    "deprecated",
)
REPORT_INTELLIGENCE_RECIPE_VALIDATION_STATUSES = (
    "candidate",
    "shadow_validated",
    "validation_candidate",
    "paper_trading_ready",
    "limited_production_ready",
    "production_ready",
    "deprecated",
)
REPORT_INTELLIGENCE_REQUIRED_DECAY_METRICS = (
    "rolling_after_cost_alpha",
    "rolling_hit_rate",
    "calibration_drift",
    "turnover_impact",
    "drawdown_after_signal",
    "half_life_estimate",
    "current_vs_backtest_performance_divergence",
)
REPORT_INTELLIGENCE_REQUIRED_ROLLBACK_MODES = (
    "soft_rollback",
    "hard_rollback",
    "compliance_rollback",
)
REPORT_INTELLIGENCE_PATCH_V1_5_SCHEMA_ARTIFACTS = (
    "report_intelligence_feature_flags.schema.json",
    "report_intelligence_report_metadata.schema.json",
    "report_intelligence_forecast_claim.schema.json",
    "report_intelligence_analytical_footprint.schema.json",
    "report_intelligence_report_forecast_ledger.schema.json",
    "report_intelligence_report_outcome_label.schema.json",
    "report_intelligence_source_performance_profile.schema.json",
    "report_intelligence_viewpoint_performance_profile.schema.json",
    "report_intelligence_method_performance_profile.schema.json",
    "report_intelligence_metric_candidate.schema.json",
    "report_intelligence_method_pattern.schema.json",
    "report_intelligence_tool_gap.schema.json",
    "report_intelligence_data_acquisition_proposal.schema.json",
    "report_intelligence_tool_design_proposal.schema.json",
    "report_intelligence_analysis_recipe.schema.json",
)
MAX_STORED_CLAIM_TEXT_CHARS = 72
ANALYTICAL_FOOTPRINT_REVIEW_BOOLEAN_FIELDS = (
    "footprint_correct",
    "source_span_supports_footprint",
    "metric_mapping_correct",
    "inferred_steps_tagged_correctly",
    "unknowns_used_when_uncertain",
    "no_proprietary_text_leakage",
)
ANALYTICAL_FOOTPRINT_REVIEW_REQUIRED_FIELDS = (
    *ANALYTICAL_FOOTPRINT_REVIEW_BOOLEAN_FIELDS,
    "reviewer",
    "review_date",
    "review_notes",
)
ANALYTICAL_FOOTPRINT_REVIEW_QUALITY_THRESHOLDS: Mapping[str, float] = {
    "footprint_precision": 0.80,
    "span_support_precision": 0.90,
    "metric_mapping_accuracy": 0.80,
    "inferred_step_tagging_accuracy": 0.80,
    "unknown_on_ambiguity_rate": 0.80,
    "proprietary_leakage_free_rate": 1.00,
}
KNOWN_AGENT_ID_PREFIXES = {
    "macro",
    "sector",
    "style",
    "portfolio",
    "risk",
    "policy",
    "market",
    "fund",
    "etf",
    "industry",
    "stock",
}


def _report_intelligence_feature_flag_payload() -> dict[str, Any]:
    return {
        "rollout_mode": REPORT_INTELLIGENCE_ROLLOUT_MODE,
        "allowed_rollout_modes": list(REPORT_INTELLIGENCE_ROLLOUT_MODES),
        "flags": dict(REPORT_INTELLIGENCE_FEATURE_FLAGS),
        "runtime_behavior": (
            "shadow retrieval and shadow tooling only; no agent decision impact; "
            "no trade without current data confirmation, validated recipes, paper "
            "trading gates, and production promotion approval"
        ),
    }
INDUSTRY_ETF_PROXY_WINDOWS_DAYS = (20, 60, 120)
INDUSTRY_ETF_PROXY_WINDOW_EFFECTIVE_WEIGHTS: Mapping[str, float] = {
    "short": 0.25,
    "medium": 0.35,
    "long": 0.40,
}
INDUSTRY_ETF_OUTCOME_LABEL_SOURCE = "pit_industry_etf_price_window"
INDUSTRY_ETF_DECISION_BASIS = "absolute_proxy_return_direction"
INDUSTRY_ETF_ENTRY_LAG_TRADING_DAYS = 1
INDUSTRY_ETF_ROUND_TRIP_COST = 0.001
INDUSTRY_ETF_EVALUATION_POLICY = (
    "industry_etf_t_plus_1_multi_window_proxy_retains_long_horizon_evidence"
)
INDUSTRY_ETF_MAPPING_VERSION = 1
INDUSTRY_ETF_BENCHMARK_SOURCE = "cn_etf"
INDUSTRY_ETF_BENCHMARK_FAMILY = "CSI300_ETF_PROXY"
INDUSTRY_ETF_COST_MODEL_ID = "industry_etf_round_trip_10bps_v1"
INDUSTRY_ETF_PROXY_MAPPING: Mapping[str, Mapping[str, str]] = {
    "工业金属": {"etf_symbol": "SH512400", "mapping_label": "有色ETF"},
    "有色金属": {"etf_symbol": "SH512400", "mapping_label": "有色ETF"},
    "贵金属": {"etf_symbol": "SH512400", "mapping_label": "有色ETF"},
    "银行": {"etf_symbol": "SH512800", "mapping_label": "银行ETF"},
    "银行Ⅱ": {"etf_symbol": "SH512800", "mapping_label": "银行ETF"},
    "证券": {"etf_symbol": "SH512880", "mapping_label": "证券ETF"},
    "证券Ⅱ": {"etf_symbol": "SH512880", "mapping_label": "证券ETF"},
    "多元金融": {"etf_symbol": "SH512880", "mapping_label": "证券ETF"},
    "半导体": {"etf_symbol": "SH512480", "mapping_label": "半导体ETF"},
    "电池": {"etf_symbol": "SH515700", "mapping_label": "新能源车ETF"},
    "汽车零部件": {"etf_symbol": "SH515700", "mapping_label": "新能源车ETF"},
    "医药商业": {"etf_symbol": "SH512170", "mapping_label": "医疗ETF"},
    "化学制药": {"etf_symbol": "SH512170", "mapping_label": "医疗ETF"},
    "房地产开发": {"etf_symbol": "SH512200", "mapping_label": "房地产ETF"},
    "航天装备Ⅱ": {"etf_symbol": "SH512660", "mapping_label": "军工ETF"},
    "风电设备": {"etf_symbol": "SH516160", "mapping_label": "新能源ETF"},
    "光伏设备": {"etf_symbol": "SH516160", "mapping_label": "新能源ETF"},
}
INDUSTRY_ETF_BENCHMARK_SYMBOL = "SH510300"
STOCK_PRICE_PROXY_WINDOWS_DAYS = (5, 20, 60, 120)
STOCK_PRICE_PROXY_WINDOW_EFFECTIVE_WEIGHTS: Mapping[int, float] = {
    5: 0.20,
    20: 0.25,
    60: 0.25,
    120: 0.30,
}
STOCK_PRICE_PROXY_ENTRY_LAG_TRADING_DAYS = 1
STOCK_PRICE_PROXY_ROUND_TRIP_COST = 0.002
STOCK_PRICE_PROXY_OUTCOME_LABEL_SOURCE = "pit_stock_price_window"
STOCK_PRICE_PROXY_BENCHMARK_SYMBOL = INDUSTRY_ETF_BENCHMARK_SYMBOL
STOCK_PRICE_PROXY_BENCHMARK_SOURCE = INDUSTRY_ETF_BENCHMARK_SOURCE
STOCK_PRICE_PROXY_BENCHMARK_FAMILY = INDUSTRY_ETF_BENCHMARK_FAMILY
STOCK_PRICE_PROXY_COST_MODEL_ID = "single_stock_round_trip_20bps_v1"
STOCK_PRICE_PROXY_DECISION_BASIS = "directional_stock_return_and_relative_alpha"
STOCK_PRICE_PROXY_EVALUATION_POLICY = (
    "stock_t_plus_1_multi_window_proxy_retains_long_horizon_evidence"
)
STOCK_PRICE_PROXY_SURVIVORSHIP_CHECK = "survivorship_unverified_qlib_cn_data"
MARKDOWN_COVERAGE_MIN_SELECTED_REPORTS = 300
MARKDOWN_COVERAGE_MIN_MARKDOWN_READY = 300
MARKDOWN_COVERAGE_MIN_QUALITY_PASS = 300
MARKDOWN_COVERAGE_MIN_LLM_EXTRACTION_PROCESSED = 100
MARKDOWN_QUALITY_MIN_BYTES = 80
MARKDOWN_QUALITY_EMPTY_TABLE_RATIO_MAX = 0.60
MARKDOWN_QUALITY_REPEATED_LINE_RATIO_MAX = 0.45
MARKDOWN_QUALITY_REPEATED_LINE_MIN_COUNT = 4
MARKDOWN_STRUCTURE_MARKERS = (
    "#",
    "##",
    "报告",
    "摘要",
    "投资",
    "评级",
    "行业",
    "公司",
    "表",
    "|",
)
EVOLUTION_GATE_MIN_UNIQUE_OUTCOME_CLAIMS = 100
EVOLUTION_GATE_MIN_STOCK_PROXY_CLAIMS = 30
EVOLUTION_GATE_MIN_INDUSTRY_PROXY_CLAIMS = 30
EVOLUTION_GATE_MIN_PAPER_TRADING_RECIPES = 20
EVOLUTION_GATE_MIN_CONSECUTIVE_MONITOR_REFRESHES = 3
EVOLUTION_GATE_MIN_CONSECUTIVE_AUDIT_REFRESHES = 3
EVOLUTION_GATE_MIN_GAP_DISTRIBUTION_REFRESHES = 3
EVOLUTION_REFRESH_HISTORY_MAX_ROWS = 50
REPORT_INTELLIGENCE_PROXY_LABEL_TYPES = frozenset(
    {"industry_etf_proxy", "stock_price_proxy"}
)

JsonMapping = Mapping[str, Any]
PdfDownloader = Callable[[str, Path, bool], Mapping[str, Any]]
PdfConverter = Callable[[Path, Path, Path, bool], Mapping[str, Any]]
LlmExtractor = Callable[[Mapping[str, Any], str, str, int, int], Mapping[str, Any]]


@dataclass(frozen=True)
class ReportIntelligenceConfig:
    root: str | Path = "."
    source_path: str | Path = TUSHARE_REPORT_SOURCE_PATH
    registry_dir: str | Path = REPORT_INTELLIGENCE_REGISTRY_DIR
    cache_dir: str | Path = REPORT_INTELLIGENCE_CACHE_DIR
    source_ids: Sequence[str] = ()
    limit: int | None = None
    min_publish_date: str | None = None
    max_publish_date: str | None = None
    selection_order: Literal["latest", "oldest"] = "latest"
    overwrite: bool = False
    skip_download: bool = False
    skip_convert: bool = False
    skip_llm: bool = False
    refresh_derived_only: bool = False
    download_timeout_seconds: int = 60
    mineru_command: str = "mineru"
    mineru_backend: str = DEFAULT_MINERU_BACKEND
    mineru_server_url: str | None = None
    mineru_args_template: str = DEFAULT_MINERU_ARGS_TEMPLATE
    mineru_timeout_seconds: int = 900
    mineru_batch_size: int = 4
    mineru_batch_max_bytes: int = 5_000_000
    vllm_base_url: str = DEFAULT_VLLM_BASE_URL
    vllm_model: str | None = None
    qlib_etf_dir: str | Path = DEFAULT_Q_LIB_ETF_PATH
    qlib_stock_dir: str | Path = DEFAULT_Q_LIB_STOCK_PATH
    vllm_timeout_seconds: int = 120
    chunk_chars: int = 60_000
    max_chunks: int = 8
    max_llm_output_tokens: int = 4096


@dataclass(frozen=True)
class ReportIntelligenceRunResult:
    run_id: str
    root: str
    selected_reports: int
    metadata_rows: int
    forecast_claim_rows: int
    analytical_footprint_rows: int
    metric_candidate_rows: int
    method_pattern_rows: int
    tool_gap_rows: int
    forecast_ledger_rows: int
    outcome_label_rows: int
    industry_etf_proxy_outcome_label_rows: int
    industry_etf_proxy_eligible_claim_rows: int
    industry_etf_proxy_labelable_window_rows: int
    industry_etf_proxy_pending_window_rows: int
    stock_price_proxy_outcome_label_rows: int
    stock_price_proxy_eligible_claim_rows: int
    stock_price_proxy_labelable_window_rows: int
    stock_price_proxy_pending_window_rows: int
    source_performance_profile_rows: int
    viewpoint_performance_profile_rows: int
    method_performance_profile_rows: int
    tool_coverage_match_rows: int
    data_acquisition_proposal_rows: int
    tool_design_proposal_rows: int
    analysis_recipe_rows: int
    prompt_mutation_candidate_rows: int
    weighted_research_context_rows: int
    runtime_tool_gap_observation_rows: int
    outcome_labeling_ready_count: int
    outcome_labeling_blocked_count: int
    pdf_ready_count: int
    markdown_ready_count: int
    llm_processed_reports: int
    blocker_count: int
    blockers: Sequence[str]
    outputs: Mapping[str, str]


@dataclass(frozen=True)
class AnalyticalFootprintReviewImportInvalidRow:
    row_number: int
    row_id: str
    reasons: Sequence[str]


@dataclass(frozen=True)
class AnalyticalFootprintReviewImportReport:
    report_id: str
    input_path: str
    target_path: str
    dry_run: bool
    accepted: bool
    input_rows: int
    applied_rows: int
    rejected_rows: int
    duplicate_ids: Sequence[str]
    missing_target_ids: Sequence[str]
    invalid_rows: Sequence[AnalyticalFootprintReviewImportInvalidRow]
    summary_path: str
    blockers: Sequence[str]


@dataclass(frozen=True)
class MineruBatchConversionTask:
    source_id: str
    pdf_path: Path
    markdown_path: Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_pit_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized):
            parsed = datetime.fromisoformat(normalized).replace(tzinfo=timezone.utc)
        else:
            parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_pit_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _max_pit_datetime(
    rows: Sequence[Mapping[str, Any]],
    *,
    fields: Sequence[str],
) -> datetime | None:
    values: list[datetime] = []
    for row in rows:
        for field in fields:
            parsed = _parse_pit_datetime(row.get(field))
            if parsed is not None:
                values.append(parsed)
                break
    return max(values) if values else None


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return {"path": str(path), "rows": 1}


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(_jsonable(row), ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    return {"path": str(path), "rows": len(rows)}


def _read_registry_jsonl(
    path: Path,
    *,
    label: str,
    blockers: list[str],
) -> list[Mapping[str, Any]]:
    if not path.exists():
        blockers.append(f"{label}: missing")
        return []
    rows, parse_blockers = load_jsonl_with_errors(path, label=label)
    blockers.extend(parse_blockers)
    valid_rows: list[Mapping[str, Any]] = []
    for index, row in enumerate(rows, 1):
        if isinstance(row, Mapping):
            valid_rows.append(row)
        else:
            blockers.append(f"{label} row {index}: expected object")
    return valid_rows


def _read_registry_json(
    path: Path,
    *,
    label: str,
    blockers: list[str],
) -> Mapping[str, Any]:
    if not path.exists():
        blockers.append(f"{label}: missing")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        blockers.append(f"{label}: invalid json: {exc.msg}")
        return {}
    if not isinstance(payload, Mapping):
        blockers.append(f"{label}: expected object")
        return {}
    return payload


def _read_schema_validation_report(root_path: Path) -> Mapping[str, Any]:
    blockers: list[str] = []
    return _read_registry_json(
        root_path / "registry/schemas/rke_schema_validation_report.json",
        label="schema_validation_report",
        blockers=blockers,
    )


def _safe_file_id(value: object) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return safe[:180] or "unknown"


def _stable_digest(payload: Mapping[str, Any], *, length: int = 16) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()[:length]


def _stable_id(prefix: str, payload: Mapping[str, Any]) -> str:
    return f"{prefix}-{_stable_digest(payload)}"


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _relative_or_absolute(path: Path, root_path: Path) -> str:
    try:
        return str(path.relative_to(root_path))
    except ValueError:
        return str(path)


def _report_intelligence_registry_path(
    *,
    root_path: Path,
    registry_dir: Path,
    relative_path: str,
) -> Path:
    path = Path(relative_path)
    default_registry = Path(REPORT_INTELLIGENCE_REGISTRY_DIR)
    if path.parts[: len(default_registry.parts)] == default_registry.parts:
        return registry_dir / path.relative_to(default_registry)
    return root_path / path


def _report_intelligence_paths_exist(
    *,
    root_path: Path,
    registry_dir: Path,
    paths: Sequence[str],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            relative
            for relative in paths
            if _report_intelligence_registry_path(
                root_path=root_path,
                registry_dir=registry_dir,
                relative_path=relative,
            ).exists()
        )
    )


def _missing_report_intelligence_private_inputs(
    *,
    root_path: Path,
    registry_dir: Path,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            relative
            for relative in REPORT_INTELLIGENCE_REQUIRED_PRIVATE_DERIVED_INPUT_PATHS
            if not _report_intelligence_registry_path(
                root_path=root_path,
                registry_dir=registry_dir,
                relative_path=relative,
            ).exists()
        )
    )


def _blocked_report_intelligence_derived_refresh_result(
    *,
    root_path: Path,
    registry_dir: Path,
    run_id: str,
    blockers: Sequence[str],
) -> ReportIntelligenceRunResult:
    outputs = {
        Path(relative).stem: _relative_or_absolute(
            _report_intelligence_registry_path(
                root_path=root_path,
                registry_dir=registry_dir,
                relative_path=relative,
            ),
            root_path,
        )
        for relative in sorted(REPORT_INTELLIGENCE_PUBLIC_DERIVED_OUTPUT_PATHS)
    }
    return ReportIntelligenceRunResult(
        run_id=run_id,
        root=str(root_path),
        selected_reports=0,
        metadata_rows=0,
        forecast_claim_rows=0,
        analytical_footprint_rows=0,
        metric_candidate_rows=0,
        method_pattern_rows=0,
        tool_gap_rows=0,
        forecast_ledger_rows=0,
        outcome_label_rows=0,
        industry_etf_proxy_outcome_label_rows=0,
        industry_etf_proxy_eligible_claim_rows=0,
        industry_etf_proxy_labelable_window_rows=0,
        industry_etf_proxy_pending_window_rows=0,
        stock_price_proxy_outcome_label_rows=0,
        stock_price_proxy_eligible_claim_rows=0,
        stock_price_proxy_labelable_window_rows=0,
        stock_price_proxy_pending_window_rows=0,
        source_performance_profile_rows=0,
        viewpoint_performance_profile_rows=0,
        method_performance_profile_rows=0,
        tool_coverage_match_rows=0,
        data_acquisition_proposal_rows=0,
        tool_design_proposal_rows=0,
        analysis_recipe_rows=0,
        prompt_mutation_candidate_rows=0,
        weighted_research_context_rows=0,
        runtime_tool_gap_observation_rows=0,
        outcome_labeling_ready_count=0,
        outcome_labeling_blocked_count=0,
        pdf_ready_count=0,
        markdown_ready_count=0,
        llm_processed_reports=0,
        blocker_count=len(blockers),
        blockers=tuple(blockers),
        outputs=outputs,
    )


def _redact_runtime_text(value: Any, root_path: Path) -> str:
    text = str(value or "")
    if not text:
        return ""
    replacements = {
        str(root_path): "<repo_root>",
        str(root_path.home()): "<home>",
    }
    for needle, replacement in replacements.items():
        if needle:
            text = text.replace(needle, replacement)
    text = re.sub(r"\b(?:sk|tp)-[A-Za-z0-9_-]{16,}\b", "<redacted-token>", text)
    text = re.sub(
        r"(?i)\b([A-Z0-9_]*(?:token|api[_-]?key|key|secret|password)[A-Z0-9_]*)"
        r"\s*[:=]\s*[^,\s]+",
        r"\1=<redacted>",
        text,
    )
    return text


def _mapping_rows(rows: Sequence[Any], blockers: list[str]) -> list[Mapping[str, Any]]:
    valid: list[Mapping[str, Any]] = []
    for index, row in enumerate(rows, 1):
        if isinstance(row, Mapping):
            valid.append(row)
        else:
            blockers.append(f"source row {index} must be object")
    return valid


def _source_file(root_path: Path, source_path: str | Path) -> Path:
    path = Path(source_path)
    return path if path.is_absolute() else root_path / path


def _selected_source_rows(
    root_path: Path,
    *,
    source_path: str | Path,
    source_ids: Sequence[str],
    limit: int | None,
    min_publish_date: str | None = None,
    max_publish_date: str | None = None,
    selection_order: Literal["latest", "oldest"] = "latest",
) -> tuple[list[Mapping[str, Any]], list[str]]:
    raw_rows, parse_blockers = load_jsonl_with_errors(
        _source_file(root_path, source_path),
        label="report source",
    )
    blockers = list(parse_blockers)
    rows = _mapping_rows(raw_rows, blockers)
    wanted = {str(source_id) for source_id in source_ids if str(source_id).strip()}
    if wanted:
        rows = [row for row in rows if str(row.get("source_id") or "") in wanted]
    if min_publish_date:
        rows = [
            row
            for row in rows
            if str(row.get("publish_date") or "") >= min_publish_date
        ]
    if max_publish_date:
        rows = [
            row
            for row in rows
            if str(row.get("publish_date") or "") <= max_publish_date
        ]
    if selection_order not in {"latest", "oldest"}:
        blockers.append("selection_order must be latest or oldest")
        selection_order = "latest"
    rows = sorted(
        rows,
        key=lambda row: (
            str(row.get("publish_date") or ""),
            str(row.get("source_id") or ""),
        ),
        reverse=selection_order == "latest",
    )
    if limit is not None:
        rows = rows[: max(limit, 0)]
    return rows, blockers


def download_pdf(
    url: str,
    pdf_path: Path,
    overwrite: bool,
    *,
    timeout_seconds: int = 60,
) -> Mapping[str, Any]:
    if pdf_path.exists() and pdf_path.stat().st_size > 0 and not overwrite:
        return {
            "status": "cached",
            "path": str(pdf_path),
            "bytes": pdf_path.stat().st_size,
            "sha256": _file_sha256(pdf_path),
        }
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "MOSAIC-RKE/0.1 local report intelligence "
                "(PDF original text materialization)"
            )
        },
    )
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            content = response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"status": "blocked", "blocker": f"pdf_download_failed: {exc}"}
    if not content:
        return {"status": "blocked", "blocker": "pdf_download_failed: empty body"}
    pdf_path.write_bytes(content)
    return {
        "status": "downloaded",
        "path": str(pdf_path),
        "bytes": len(content),
        "sha256": _file_sha256(pdf_path),
    }


def _format_mineru_args(
    args_template: str,
    *,
    pdf_path: Path,
    output_dir: Path,
    backend: str,
    server_url: str | None,
) -> list[str]:
    formatted = args_template.format(
        pdf=str(pdf_path),
        output_dir=str(output_dir),
        output=str(output_dir),
        backend=backend,
    )
    args = shlex.split(formatted)
    if server_url and "-u" not in args and "--url" not in args:
        args.extend(["-u", server_url])
    return args


def _largest_markdown_file(output_dir: Path) -> Path | None:
    markdowns = [
        path
        for path in output_dir.rglob("*.md")
        if path.is_file() and path.stat().st_size > 0
    ]
    if not markdowns:
        return None
    return max(markdowns, key=lambda path: (path.stat().st_size, path.stat().st_mtime))


def _markdown_file_for_stem(output_dir: Path, stem: str) -> Path | None:
    markdowns = [
        path
        for path in output_dir.rglob("*.md")
        if path.is_file() and path.stat().st_size > 0 and path.stem == stem
    ]
    if not markdowns:
        return None
    return max(markdowns, key=lambda path: (path.stat().st_size, path.stat().st_mtime))


def _decode_non_pdf_text_source(path: Path) -> str | None:
    payload = path.read_bytes()
    if payload.lstrip().startswith(b"%PDF"):
        return None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            text = payload.decode(encoding)
        except UnicodeDecodeError:
            continue
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return None
        control_count = sum(
            1
            for char in normalized
            if ord(char) < 32 and char not in {"\n", "\t", "\f"}
        )
        if control_count > max(20, int(len(normalized) * 0.02)):
            return None
        return normalized
    return None


def _convert_text_source_to_markdown(
    source_path: Path,
    markdown_path: Path,
    *,
    backend: str,
) -> Mapping[str, Any] | None:
    text = _decode_non_pdf_text_source(source_path)
    if text is None:
        return None
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(text + "\n", encoding="utf-8")
    return {
        "status": "converted_text_source",
        "path": str(markdown_path),
        "mineru_output_path": "",
        "source_format": "text",
        "backend": backend,
        "bytes": markdown_path.stat().st_size,
        "sha256": _file_sha256(markdown_path),
    }


def _mineru_executable(command: str) -> tuple[list[str], str | None]:
    command_parts = shlex.split(command)
    if not command_parts:
        return (), "mineru_command_empty"
    executable = shutil.which(command_parts[0])
    if executable is None:
        return (), f"mineru_command_not_found: {command_parts[0]}"
    return [executable, *command_parts[1:]], None


def _mineru_args(
    command: str,
    *,
    input_path: Path,
    output_dir: Path,
    backend: str,
    server_url: str | None,
    args_template: str,
) -> tuple[list[str], str | None]:
    command_parts, blocker = _mineru_executable(command)
    if blocker:
        return (), blocker
    backend = backend.strip() or DEFAULT_MINERU_BACKEND
    if backend not in MINERU_BACKENDS:
        return (), f"mineru_backend_invalid: {backend}"
    return [
        *command_parts,
        *_format_mineru_args(
            args_template,
            pdf_path=input_path,
            output_dir=output_dir,
            backend=backend,
            server_url=server_url,
        ),
    ], None


def _terminate_process_tree(pid: int) -> None:
    try:
        import psutil
    except ImportError:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                return
        return
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    processes = parent.children(recursive=True)
    processes.append(parent)
    for process in processes:
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            continue
    _, alive = psutil.wait_procs(processes, timeout=5)
    for process in alive:
        try:
            process.kill()
        except psutil.NoSuchProcess:
            continue


def _run_mineru(args: Sequence[str], *, cwd: Path, timeout_seconds: int) -> Mapping[str, Any]:
    command = " ".join(shlex.quote(part) for part in args)
    started_at = time.monotonic()
    try:
        process = subprocess.Popen(
            list(args),
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process.pid)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        duration_seconds = round(time.monotonic() - started_at, 3)
        return {
            "status": "blocked",
            "blocker": "mineru_timeout",
            "timed_out": True,
            "command": command,
            "returncode": process.returncode,
            "stderr_tail": stderr.strip()[-1000:],
            "stdout_tail": stdout.strip()[-1000:],
            "duration_seconds": duration_seconds,
        }
    duration_seconds = round(time.monotonic() - started_at, 3)
    if process.returncode == 0:
        return {"status": "ok", "duration_seconds": duration_seconds}
    return {
        "status": "blocked",
        "blocker": "mineru_failed",
        "command": command,
        "returncode": process.returncode,
        "stderr_tail": stderr.strip()[-1000:],
        "stdout_tail": stdout.strip()[-1000:],
        "duration_seconds": duration_seconds,
    }


def convert_pdf_with_mineru(
    pdf_path: Path,
    output_dir: Path,
    markdown_path: Path,
    overwrite: bool,
    *,
    command: str = "mineru",
    backend: str = DEFAULT_MINERU_BACKEND,
    server_url: str | None = None,
    args_template: str = DEFAULT_MINERU_ARGS_TEMPLATE,
    timeout_seconds: int = 900,
) -> Mapping[str, Any]:
    backend = backend.strip() or DEFAULT_MINERU_BACKEND
    if markdown_path.exists() and markdown_path.stat().st_size > 0 and not overwrite:
        return {
            "status": "cached",
            "path": str(markdown_path),
            "backend": backend,
            "bytes": markdown_path.stat().st_size,
            "sha256": _file_sha256(markdown_path),
        }
    if not pdf_path.exists() or pdf_path.stat().st_size <= 0:
        return {"status": "blocked", "blocker": "mineru_input_pdf_missing"}
    text_result = _convert_text_source_to_markdown(
        pdf_path,
        markdown_path,
        backend=backend,
    )
    if text_result is not None:
        return text_result
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    args, blocker = _mineru_args(
        command,
        input_path=pdf_path,
        output_dir=output_dir,
        backend=backend,
        server_url=server_url,
        args_template=args_template,
    )
    if blocker:
        return {"status": "blocked", "blocker": blocker}
    run_result = _run_mineru(args, cwd=output_dir, timeout_seconds=timeout_seconds)
    if run_result["status"] == "blocked":
        return run_result
    produced = _largest_markdown_file(output_dir)
    if produced is None:
        return {"status": "blocked", "blocker": "mineru_markdown_not_found"}
    shutil.copyfile(produced, markdown_path)
    return {
        "status": "converted",
        "path": str(markdown_path),
        "mineru_output_path": str(produced),
        "backend": backend,
        "bytes": markdown_path.stat().st_size,
        "sha256": _file_sha256(markdown_path),
        "duration_seconds": run_result.get("duration_seconds"),
    }


def _link_or_copy(src: Path, dst: Path) -> None:
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        dst.symlink_to(src)
        return
    except OSError:
        pass
    try:
        dst.hardlink_to(src)
        return
    except OSError:
        pass
    shutil.copyfile(src, dst)


def _batched(values: Sequence[Any], batch_size: int) -> list[Sequence[Any]]:
    size = max(int(batch_size), 1)
    return [values[index : index + size] for index in range(0, len(values), size)]


def _batched_conversion_tasks(
    tasks: Sequence[MineruBatchConversionTask],
    *,
    batch_size: int,
    max_batch_bytes: int,
) -> list[Sequence[MineruBatchConversionTask]]:
    if max_batch_bytes <= 0:
        return _batched(tuple(tasks), batch_size)
    size = max(int(batch_size), 1)
    ordered = sorted(
        tasks,
        key=lambda task: (
            task.pdf_path.stat().st_size if task.pdf_path.exists() else 0,
            task.source_id,
        ),
    )
    batches: list[list[MineruBatchConversionTask]] = []
    current: list[MineruBatchConversionTask] = []
    current_bytes = 0
    for task in ordered:
        task_bytes = task.pdf_path.stat().st_size if task.pdf_path.exists() else 0
        would_exceed_count = len(current) >= size
        would_exceed_bytes = (
            current
            and current_bytes + task_bytes > max_batch_bytes
        )
        if would_exceed_count or would_exceed_bytes:
            batches.append(current)
            current = []
            current_bytes = 0
        current.append(task)
        current_bytes += task_bytes
    if current:
        batches.append(current)
    return batches


def _blocked_mineru_result(blocker: str, *, backend: str) -> dict[str, Any]:
    return {"status": "blocked", "blocker": blocker, "backend": backend}


def _copy_batch_markdown_result(
    *,
    task: MineruBatchConversionTask,
    batch_output_dir: Path,
    backend: str,
    run_result: Mapping[str, Any],
) -> Mapping[str, Any]:
    produced = _markdown_file_for_stem(batch_output_dir, task.pdf_path.stem)
    if produced is None:
        result: dict[str, Any] = {
            "status": "blocked",
            "blocker": "mineru_markdown_not_found",
            "backend": backend,
        }
        for field in (
            "command",
            "returncode",
            "timed_out",
            "stderr_tail",
            "stdout_tail",
            "duration_seconds",
        ):
            if run_result.get(field) not in (None, ""):
                result[field] = run_result[field]
        return result
    task.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(produced, task.markdown_path)
    result = {
        "status": "converted",
        "path": str(task.markdown_path),
        "mineru_output_path": str(produced),
        "backend": backend,
        "bytes": task.markdown_path.stat().st_size,
        "sha256": _file_sha256(task.markdown_path),
    }
    if run_result.get("duration_seconds") not in (None, ""):
        result["duration_seconds"] = run_result["duration_seconds"]
    return result


def convert_pdfs_with_mineru_batch(
    tasks: Sequence[MineruBatchConversionTask],
    work_dir: Path,
    overwrite: bool,
    *,
    command: str = "mineru",
    backend: str = DEFAULT_MINERU_BACKEND,
    server_url: str | None = None,
    args_template: str = DEFAULT_MINERU_ARGS_TEMPLATE,
    timeout_seconds: int = 900,
    batch_size: int = 4,
    max_batch_bytes: int = 5_000_000,
) -> dict[str, Mapping[str, Any]]:
    backend = backend.strip() or DEFAULT_MINERU_BACKEND
    results: dict[str, Mapping[str, Any]] = {}
    pending: list[MineruBatchConversionTask] = []
    for task in tasks:
        if task.markdown_path.exists() and task.markdown_path.stat().st_size > 0 and not overwrite:
            results[task.source_id] = {
                "status": "cached",
                "path": str(task.markdown_path),
                "backend": backend,
                "bytes": task.markdown_path.stat().st_size,
                "sha256": _file_sha256(task.markdown_path),
            }
        elif not task.pdf_path.exists() or task.pdf_path.stat().st_size <= 0:
            results[task.source_id] = _blocked_mineru_result(
                "mineru_input_pdf_missing",
                backend=backend,
            )
        else:
            text_result = _convert_text_source_to_markdown(
                task.pdf_path,
                task.markdown_path,
                backend=backend,
            )
            if text_result is not None:
                results[task.source_id] = text_result
            else:
                pending.append(task)
    if not pending:
        return results
    if backend not in MINERU_BACKENDS:
        for task in pending:
            results[task.source_id] = _blocked_mineru_result(
                f"mineru_backend_invalid: {backend}",
                backend=backend,
            )
        return results
    work_dir.mkdir(parents=True, exist_ok=True)
    batches = _batched_conversion_tasks(
        pending,
        batch_size=batch_size,
        max_batch_bytes=max_batch_bytes,
    )
    for batch_index, batch in enumerate(batches, 1):
        batch_input_dir = work_dir / f"input-{batch_index:03d}"
        batch_output_dir = work_dir / f"output-{batch_index:03d}"
        batch_input_dir.mkdir(parents=True, exist_ok=True)
        batch_output_dir.mkdir(parents=True, exist_ok=True)
        for task in batch:
            _link_or_copy(task.pdf_path, batch_input_dir / task.pdf_path.name)
        args, blocker = _mineru_args(
            command,
            input_path=batch_input_dir,
            output_dir=batch_output_dir,
            backend=backend,
            server_url=server_url,
            args_template=args_template,
        )
        if blocker:
            for task in batch:
                results[task.source_id] = _blocked_mineru_result(
                    blocker,
                    backend=backend,
                )
            continue
        run_result = _run_mineru(
            args,
            cwd=batch_output_dir,
            timeout_seconds=timeout_seconds,
        )
        for task in batch:
            converted = _copy_batch_markdown_result(
                task=task,
                batch_output_dir=batch_output_dir,
                backend=backend,
                run_result=run_result,
            )
            if converted["status"] == "blocked" and run_result.get("status") == "blocked":
                converted = {**run_result, "backend": backend}
            results[task.source_id] = converted
    return results


def _url(base_url: str, suffix: str) -> str:
    return f"{base_url.rstrip('/')}/{suffix.lstrip('/')}"


def resolve_vllm_model(
    base_url: str = DEFAULT_VLLM_BASE_URL,
    *,
    explicit_model: str | None = None,
    timeout_seconds: int = 10,
) -> str:
    if explicit_model:
        return explicit_model
    try:
        with urllib.request.urlopen(
            _url(base_url, "models"),
            timeout=timeout_seconds,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"vllm_model_discovery_failed: {exc}") from exc
    data = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(data, list) or not data:
        raise RuntimeError("vllm_model_discovery_failed: no models returned")
    model_id = data[0].get("id") if isinstance(data[0], Mapping) else None
    if not str(model_id or "").strip():
        raise RuntimeError("vllm_model_discovery_failed: first model id missing")
    return str(model_id)


def _extract_json_object(text: str) -> Mapping[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            return value
    raise ValueError("llm_output_json_object_not_found")


def _chunk_text(text: str, *, chunk_chars: int, max_chunks: int) -> list[str]:
    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be positive")
    if max_chunks <= 0:
        raise ValueError("max_chunks must be positive")
    chunks: list[str] = []
    start = 0
    text_length = len(text)
    while start < text_length and len(chunks) < max_chunks:
        end = min(start + chunk_chars, text_length)
        if end < text_length:
            boundary = max(
                text.rfind("\n\n", start, end),
                text.rfind("\n#", start, end),
                text.rfind("。", start, end),
            )
            if boundary > start + int(chunk_chars * 0.5):
                end = boundary + 1
        chunks.append(text[start:end].strip())
        start = end
    return [chunk for chunk in chunks if chunk]


def _report_id(row: Mapping[str, Any]) -> str:
    source_id = str(row.get("source_id") or "")
    publish = str(row.get("publish_date") or "UNKNOWN").replace("-", "")
    digest = _stable_digest(
        {
            "source_id": source_id,
            "title": row.get("title"),
            "url": row.get("url"),
        }
    )
    return f"RPT-TSRR-{publish}-{digest}"


def _author_ids(author: object) -> list[str]:
    raw = str(author or "").strip()
    if not raw:
        return []
    parts = [part.strip() for part in re.split(r"[,，;/、\s]+", raw) if part.strip()]
    return [
        "AUTH-" + _stable_digest({"author": part}, length=12).upper()
        for part in dict.fromkeys(parts)
    ]


def _metadata_record(
    row: Mapping[str, Any],
    *,
    run_id: str,
    root_path: Path,
    pdf_result: Mapping[str, Any],
    markdown_result: Mapping[str, Any],
    llm_status: str,
    llm_model: str | None,
    chunk_count: int,
    truncated_chunks: bool,
    blockers: Sequence[str],
) -> dict[str, Any]:
    source_id = str(row.get("source_id") or "")
    publish_date = str(row.get("publish_date") or "")
    report_id = _report_id(row)
    pdf_path = Path(str(pdf_result.get("path") or "")) if pdf_result.get("path") else None
    markdown_path = (
        Path(str(markdown_result.get("path") or ""))
        if markdown_result.get("path")
        else None
    )
    return {
        "report_id": report_id,
        "source_id": source_id,
        "source_type": str(row.get("source_type") or "tushare_research_report"),
        "source_span_id": f"{source_id}:original_markdown",
        "institution_id": "INST-"
        + _stable_digest({"institution": row.get("institution")}, length=12).upper(),
        "institution": str(row.get("institution") or ""),
        "author_ids": _author_ids(row.get("author")),
        "author": str(row.get("author") or ""),
        "report_type": str(row.get("report_type") or ""),
        "market": "CN_A_SHARE",
        "asset_class": "equity",
        "sector": str(row.get("industry") or row.get("query_key") or "unknown"),
        "ts_code": str(row.get("ts_code") or ""),
        "subsectors": [],
        "title": str(row.get("title") or ""),
        "publish_datetime": f"{publish_date}T00:00:00+08:00"
        if publish_date
        else "",
        "accessible_datetime": f"{publish_date}T00:00:00+08:00"
        if publish_date
        else "",
        "language": "zh",
        "version": "original_pdf_markdown",
        "supersedes_report_id": None,
        "license_class": "operator_approved_internal_research_use",
        "redistribution_allowed": False,
        "derived_claim_storage_allowed": "operator_approved_internal_use",
        "storage_policy": "local_full_text_cache_registry_derived_metadata",
        "point_in_time_available": bool(row.get("point_in_time_available", True)),
        "source_row_license_status": str(row.get("license_status") or ""),
        "url": str(row.get("url") or ""),
        "pdf": {
            "status": pdf_result.get("status") or "not_attempted",
            "path": _relative_or_absolute(pdf_path, root_path) if pdf_path else "",
            "sha256": pdf_result.get("sha256") or "",
            "bytes": int(pdf_result.get("bytes") or 0),
        },
        "markdown": {
            "status": markdown_result.get("status") or "not_attempted",
            "path": (
                _relative_or_absolute(markdown_path, root_path)
                if markdown_path
                else ""
            ),
            "sha256": markdown_result.get("sha256") or "",
            "bytes": int(markdown_result.get("bytes") or 0),
            "backend": markdown_result.get("backend") or "",
            "blocker": markdown_result.get("blocker") or "",
            "returncode": markdown_result.get("returncode"),
            "timed_out": bool(markdown_result.get("timed_out")),
            "duration_seconds": markdown_result.get("duration_seconds"),
            "quality_gate_status": markdown_result.get("quality_gate_status") or "",
            "quality_gap": markdown_result.get("quality_gap") or "",
            "stderr_tail": _redact_runtime_text(
                markdown_result.get("stderr_tail"),
                root_path,
            ),
            "stdout_tail": _redact_runtime_text(
                markdown_result.get("stdout_tail"),
                root_path,
            ),
            "command": _redact_runtime_text(markdown_result.get("command"), root_path),
        },
        "extraction": {
            "run_id": run_id,
            "input_mode": "original_markdown",
            "abstract_only_fallback_used": False,
            "llm_status": llm_status,
            "llm_model": llm_model or "",
            "chunk_count": chunk_count,
            "truncated_after_max_chunks": truncated_chunks,
            "blockers": list(blockers),
        },
    }


def _system_prompt() -> str:
    return (
        "You are an RKE report-intelligence extractor. Use only the supplied "
        "original report Markdown chunk. Separate source-grounded facts from "
        "inferred hypotheses. Do not rely on any abstract. Do not invent exact "
        "targets, horizons, windows, formulas, or data sources when the text is "
        "ambiguous; use unknown or insufficient_mapping instead. Return only a "
        "single JSON object. Do not include thinking text, commentary, Markdown, "
        "or code fences. Metadata may identify the report entity, but source text "
        "must still support each forecast. /no_think"
    )


def _user_prompt(
    row: Mapping[str, Any],
    markdown_chunk: str,
    chunk_span_id: str,
    chunk_index: int,
    chunk_count: int,
) -> str:
    metadata = {
        "source_id": row.get("source_id"),
        "title": row.get("title"),
        "institution": row.get("institution"),
        "author": row.get("author"),
        "publish_date": row.get("publish_date"),
        "report_type": row.get("report_type"),
        "query_key": row.get("query_key"),
        "industry": row.get("industry"),
        "ts_code": row.get("ts_code"),
        "chunk_span_id": chunk_span_id,
        "chunk_index": chunk_index,
        "chunk_count": chunk_count,
    }
    return (
        "Extract Report Intelligence Loop objects for this Markdown chunk.\n"
        "Return JSON with exactly these top-level array keys: "
        "forecast_claims, analytical_footprints, metric_candidates, "
        "method_patterns, tool_gaps.\n\n"
        "forecast_claim fields: claim_text, claim_provenance "
        "(source_grounded|analyst_or_llm_hypothesis), forecast_testability "
        "(testable|non_testable|insufficient_mapping), forecast_type, target, "
        "benchmark, direction (positive|negative|neutral|ambiguous|unknown), "
        "horizon, explicitness (explicit|inferred|unknown), source_conviction, "
        "metric_proxy_mapping, failure_modes, extraction_quality.\n"
        "For stock reports, if Report metadata.ts_code is present and the chunk "
        "contains a forecast, rating, or investment view for that same company, "
        "set target.target_type='stock' and target.target_id to metadata.ts_code. "
        "If the text names a benchmark, include benchmark_id; otherwise use "
        "benchmark_type='broad_market' only when the text frames a relative call "
        "against the market. Never invent a horizon; keep horizon unknown when "
        "the source text has no explicit or clearly implied time window.\n"
        "analytical_footprints fields: topic, indicator_mentions, "
        "analysis_patterns, target_agent_candidates. Mark each mention/step "
        "with source_grounded true/false when possible.\n"
        "metric_candidates fields: canonical_name, aliases, metric_family, "
        "raw_data_requirements, default_transformation, target_agents.\n"
        "method_patterns fields: name, steps, required_current_data, "
        "optional_confirmation_data, failure_modes, target_agents.\n"
        "tool_gaps fields: gap_type, metric_name, method_name, target_agents, "
        "priority_reasons, blocking_issues.\n\n"
        "Use this chunk span id for source-grounded records: "
        f"{chunk_span_id}\n\n"
        "Report metadata:\n"
        f"{json.dumps(metadata, ensure_ascii=False, sort_keys=True)}\n\n"
        "Original Markdown chunk:\n"
        f"{markdown_chunk}"
    )


def call_vllm_extractor(
    row: Mapping[str, Any],
    markdown_chunk: str,
    chunk_span_id: str,
    chunk_index: int,
    chunk_count: int,
    *,
    base_url: str = DEFAULT_VLLM_BASE_URL,
    model: str | None = None,
    timeout_seconds: int = 120,
    max_output_tokens: int = 4096,
) -> Mapping[str, Any]:
    resolved_model = resolve_vllm_model(
        base_url,
        explicit_model=model,
        timeout_seconds=min(timeout_seconds, 30),
    )
    payload = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": _user_prompt(
                    row,
                    markdown_chunk,
                    chunk_span_id,
                    chunk_index,
                    chunk_count,
                ),
            },
        ],
        "temperature": 0,
        "max_tokens": max_output_tokens,
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        _url(base_url, "chat/completions"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {
            "status": "blocked",
            "blocker": f"vllm_request_failed: {exc}",
            "model": resolved_model,
        }
    choices = response_payload.get("choices") if isinstance(response_payload, Mapping) else None
    if not isinstance(choices, list) or not choices:
        return {
            "status": "blocked",
            "blocker": "vllm_response_choices_missing",
            "model": resolved_model,
        }
    first = choices[0] if isinstance(choices[0], Mapping) else {}
    message = first.get("message") if isinstance(first, Mapping) else {}
    content = message.get("content") if isinstance(message, Mapping) else ""
    try:
        extracted = _extract_json_object(str(content or ""))
    except ValueError as exc:
        return {
            "status": "blocked",
            "blocker": str(exc),
            "model": resolved_model,
            "content_tail": str(content or "")[-1000:],
        }
    return {"status": "ok", "model": resolved_model, "payload": extracted}


def _ensure_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _ensure_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _stable_item_key(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True)


def _merge_unique_values(existing: list[Any], additions: Sequence[Any]) -> list[Any]:
    out = list(existing)
    seen = {_stable_item_key(item) for item in out}
    for item in additions:
        key = _stable_item_key(item)
        if key not in seen:
            out.append(item)
            seen.add(key)
    return out


def _record_text(value: Any, *fields: str) -> str:
    mapping = _ensure_mapping(value)
    for field in fields:
        text = str(mapping.get(field) or "").strip()
        if text:
            return text
    return ""


def _bounded_claim_text(text: str) -> tuple[str, bool]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= MAX_STORED_CLAIM_TEXT_CHARS:
        return normalized, False
    return normalized[: MAX_STORED_CLAIM_TEXT_CHARS - 3].rstrip() + "...", True


def _normalize_failure_modes(value: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in _ensure_list(value):
        if isinstance(item, Mapping):
            text = _record_text(item, "text", "failure_mode", "name")
            if not text:
                continue
            provenance = str(item.get("provenance") or "analyst_or_llm_hypothesis")
            requires_independent_validation = item.get(
                "requires_independent_validation"
            )
        else:
            text = str(item or "").strip()
            if not text:
                continue
            provenance = "analyst_or_llm_hypothesis"
            requires_independent_validation = True
        records.append(
            {
                "text": text,
                "provenance": provenance,
                "requires_independent_validation": bool(
                    True
                    if requires_independent_validation is None
                    else requires_independent_validation
                ),
            }
        )
    return records


def _indicator_value_unknown(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {"", "unknown", "n/a", "na", "none", "null"}


INDICATOR_METADATA_RULES: tuple[tuple[str, Mapping[str, Any]], ...] = (
    (
        r"\bdr\s*007\b|dr007|policy[_\s-]*rate|政策利率",
        {
            "canonical_metric_candidate": "dr007_policy_rate_spread",
            "data_source_mentioned": "interbank_repo_rate_and_policy_rate",
            "frequency": "daily",
            "transformation": "spread",
            "role_in_argument": "funding_stress_proxy",
        },
    ),
    (
        r"\bphase\s*(i|ii|iii|1|2|3)\b|clinical|trial|registration|asco",
        {
            "canonical_metric_candidate": "clinical_trial_milestone_status",
            "data_source_mentioned": "company_disclosure_or_clinical_trial_registry",
            "frequency": "event_driven",
            "transformation": "milestone_event",
            "role_in_argument": "clinical_development_milestone",
        },
    ),
    (
        r"\bdcf\b|discounted[_\s-]*cash[_\s-]*flow",
        {
            "canonical_metric_candidate": "dcf_valuation_model",
            "data_source_mentioned": "report_valuation_model",
            "frequency": "point_in_time",
            "transformation": "valuation_model",
            "role_in_argument": "valuation_method",
        },
    ),
    (
        r"\bwacc\b|weighted[_\s-]*average[_\s-]*cost[_\s-]*of[_\s-]*capital",
        {
            "canonical_metric_candidate": "weighted_average_cost_of_capital",
            "data_source_mentioned": "report_valuation_assumption",
            "frequency": "point_in_time",
            "transformation": "extract_assumption",
            "role_in_argument": "discount_rate_assumption",
        },
    ),
    (
        r"target[_\s-]*price|price[_\s-]*target|目标价",
        {
            "canonical_metric_candidate": "target_price",
            "data_source_mentioned": "report_valuation_output",
            "frequency": "point_in_time",
            "transformation": "extract_forecast",
            "role_in_argument": "valuation_output",
        },
    ),
    (
        r"net[_\s-]*profit|归母净利润|净利润",
        {
            "canonical_metric_candidate": "forecast_net_profit",
            "data_source_mentioned": "report_financial_forecast",
            "frequency": "annual",
            "transformation": "extract_forecast",
            "role_in_argument": "earnings_forecast_metric",
        },
    ),
    (
        r"\beps\b|earnings[_\s-]*per[_\s-]*share",
        {
            "canonical_metric_candidate": "forecast_eps",
            "data_source_mentioned": "report_financial_forecast",
            "frequency": "annual",
            "transformation": "extract_forecast",
            "role_in_argument": "earnings_forecast_metric",
        },
    ),
    (
        r"gross[_\s-]*margin|毛利率",
        {
            "canonical_metric_candidate": "forecast_gross_margin",
            "data_source_mentioned": "report_financial_forecast",
            "frequency": "annual",
            "transformation": "extract_forecast",
            "role_in_argument": "profitability_forecast_metric",
        },
    ),
    (
        r"non[_\s-]*banking[_\s-]*financial[_\s-]*index",
        {
            "canonical_metric_candidate": "non_banking_financial_index_return",
            "data_source_mentioned": "exchange_index_price",
            "frequency": "daily",
            "transformation": "return",
            "role_in_argument": "sector_relative_performance_proxy",
        },
    ),
    (
        r"brokerage[_\s-]*index|insurance[_\s-]*index|shanghai[_\s-]*composite[_\s-]*index|shenzhen[_\s-]*component[_\s-]*index|gem[_\s-]*index",
        {
            "canonical_metric_candidate": "market_or_sector_index_return",
            "data_source_mentioned": "exchange_index_price",
            "frequency": "daily",
            "transformation": "return",
            "role_in_argument": "relative_performance_proxy",
        },
    ),
    (
        r"\bpb[_\s-]*valuation\b|\bpb\b|price[_\s-]*to[_\s-]*book",
        {
            "canonical_metric_candidate": "price_to_book_ratio",
            "data_source_mentioned": "market_valuation_data",
            "frequency": "daily",
            "transformation": "valuation_ratio",
            "role_in_argument": "valuation_proxy",
        },
    ),
    (
        r"\bm[_\s-]*a[_\s-]*deals\b|merger|acquisition",
        {
            "canonical_metric_candidate": "brokerage_m_and_a_deal_activity",
            "data_source_mentioned": "corporate_action_or_exchange_disclosure",
            "frequency": "event_driven",
            "transformation": "event_count",
            "role_in_argument": "industry_consolidation_proxy",
        },
    ),
    (
        r"regulatory[_\s-]*approval",
        {
            "canonical_metric_candidate": "regulatory_approval_status",
            "data_source_mentioned": "regulatory_disclosure",
            "frequency": "event_driven",
            "transformation": "status_event",
            "role_in_argument": "policy_or_transaction_catalyst",
        },
    ),
    (
        r"premium[_\s-]*income|life[_\s-]*insurance[_\s-]*premiums|property[_\s-]*insurance[_\s-]*premiums",
        {
            "canonical_metric_candidate": "insurance_premium_income",
            "data_source_mentioned": "insurance_company_or_regulatory_disclosure",
            "frequency": "monthly",
            "transformation": "growth_rate",
            "role_in_argument": "insurance_business_growth_metric",
        },
    ),
    (
        r"claim[_\s-]*payout",
        {
            "canonical_metric_candidate": "insurance_claim_payouts",
            "data_source_mentioned": "insurance_company_or_regulatory_disclosure",
            "frequency": "monthly",
            "transformation": "growth_rate",
            "role_in_argument": "insurance_loss_ratio_proxy",
        },
    ),
    (
        r"insurance[_\s-]*assets",
        {
            "canonical_metric_candidate": "insurance_total_assets",
            "data_source_mentioned": "insurance_company_or_regulatory_disclosure",
            "frequency": "quarterly",
            "transformation": "level_or_growth",
            "role_in_argument": "insurance_balance_sheet_metric",
        },
    ),
    (
        r"equity[_\s-]*financing[_\s-]*scale|ipo[_\s-]*amount|refinancing[_\s-]*amount",
        {
            "canonical_metric_candidate": "equity_financing_scale",
            "data_source_mentioned": "exchange_or_wind_financing_data",
            "frequency": "monthly",
            "transformation": "sum",
            "role_in_argument": "capital_market_activity_metric",
        },
    ),
    (
        r"bond[_\s-]*underwriting[_\s-]*scale",
        {
            "canonical_metric_candidate": "bond_underwriting_scale",
            "data_source_mentioned": "bond_market_issuance_data",
            "frequency": "monthly",
            "transformation": "sum",
            "role_in_argument": "capital_market_activity_metric",
        },
    ),
    (
        r"asset[_\s-]*management[_\s-]*issuance",
        {
            "canonical_metric_candidate": "asset_management_product_issuance",
            "data_source_mentioned": "asset_management_product_disclosure",
            "frequency": "monthly",
            "transformation": "sum",
            "role_in_argument": "wealth_management_activity_metric",
        },
    ),
    (
        r"margin[_\s-]*trading[_\s-]*balance",
        {
            "canonical_metric_candidate": "margin_trading_balance",
            "data_source_mentioned": "exchange_margin_financing_data",
            "frequency": "daily",
            "transformation": "level_or_change",
            "role_in_argument": "market_risk_appetite_metric",
        },
    ),
    (
        r"pledge[_\s-]*share[_\s-]*count",
        {
            "canonical_metric_candidate": "pledged_share_count",
            "data_source_mentioned": "share_pledge_disclosure",
            "frequency": "daily",
            "transformation": "level_or_change",
            "role_in_argument": "equity_pledge_risk_metric",
        },
    ),
)


def _infer_indicator_metadata(indicator_text: str) -> dict[str, Any]:
    for pattern, metadata in INDICATOR_METADATA_RULES:
        if re.search(pattern, indicator_text, flags=re.IGNORECASE):
            inferred = dict(metadata)
            inferred["source_grounded"] = True
            return inferred
    return {}


def _apply_indicator_metadata_inference(mention: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(mention)
    indicator_text = _record_text(
        normalized,
        "indicator_text",
        "canonical_metric_candidate",
        "canonical_name",
    )
    inferred = _infer_indicator_metadata(indicator_text)
    for field in (
        "canonical_metric_candidate",
        "data_source_mentioned",
        "frequency",
        "transformation",
        "role_in_argument",
    ):
        if _indicator_value_unknown(normalized.get(field)) and field in inferred:
            normalized[field] = inferred[field]
    if inferred and normalized.get("source_grounded") is not True:
        normalized["source_grounded"] = True
    return normalized


def _normalize_indicator_mentions(value: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in _ensure_list(value):
        if isinstance(item, Mapping):
            mention = dict(item)
            indicator_text = _record_text(
                mention,
                "indicator_text",
                "canonical_metric_candidate",
                "canonical_name",
            )
            if not indicator_text:
                continue
            mention.setdefault("indicator_text", indicator_text)
            mention.setdefault("canonical_metric_candidate", "unknown")
            mention.setdefault("data_source_mentioned", "unknown")
            mention.setdefault("frequency", "unknown")
            mention.setdefault("lookback_window", {})
            mention.setdefault("transformation", "unknown")
            mention.setdefault("role_in_argument", "unknown")
            mention.setdefault("source_grounded", False)
            mention = _apply_indicator_metadata_inference(mention)
            records.append(mention)
            continue
        indicator_text = str(item or "").strip()
        if not indicator_text:
            continue
        records.append(
            _apply_indicator_metadata_inference(
                {
                    "indicator_text": indicator_text,
                    "canonical_metric_candidate": "unknown",
                    "data_source_mentioned": "unknown",
                    "frequency": "unknown",
                    "lookback_window": {},
                    "transformation": "unknown",
                    "role_in_argument": "unknown",
                    "source_grounded": False,
                }
            )
        )
    return records


def _source_span_ids(value: Mapping[str, Any], fallback_span_id: str) -> list[str]:
    span_ids = [
        str(item)
        for item in _ensure_list(value.get("source_span_ids"))
        if str(item).strip()
    ]
    if not span_ids and str(value.get("source_span_id") or "").strip():
        span_ids = [str(value["source_span_id"])]
    return span_ids or [fallback_span_id]


def _known_agent_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower().replace("-", "_")
    lowered = re.sub(r"[^a-z0-9_.]+", "_", lowered)
    lowered = re.sub(r"_+", "_", lowered).strip("_.")
    if (
        re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+", lowered)
        and lowered.split(".", 1)[0] in KNOWN_AGENT_ID_PREFIXES
    ):
        return lowered
    return ""


def _split_agent_and_entity_candidates(values: Any) -> tuple[list[str], list[str]]:
    agents: list[str] = []
    entities: list[str] = []
    for value in _ensure_list(values):
        raw = str(value or "").strip()
        if not raw:
            continue
        agent_id = _known_agent_id(raw)
        if agent_id:
            agents.append(agent_id)
        else:
            entities.append(raw)
    return list(dict.fromkeys(agents)), list(dict.fromkeys(entities))


def _normalize_forecast_direction(value: Any) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "bullish": "positive",
        "bearish": "negative",
        "down": "negative",
        "mixed": "ambiguous",
        "up": "positive",
        "多": "positive",
        "多头": "positive",
        "看多": "positive",
        "看空": "negative",
        "空": "negative",
        "空头": "negative",
        "中性": "neutral",
        "不确定": "ambiguous",
    }
    normalized = aliases.get(text, text)
    if normalized in {"positive", "negative", "neutral", "ambiguous", "unknown"}:
        return normalized
    return "unknown"


def _duration_to_days(value: float, unit: str) -> int | None:
    normalized = unit.strip()
    if normalized in {"交易日"}:
        return max(1, int(round(value)))
    if normalized in {"天", "日"}:
        return max(1, int(round(value)))
    if normalized in {"周"}:
        return max(1, int(round(value * 7)))
    if normalized in {"个月", "月"}:
        return max(1, int(round(value * 30.4375)))
    if normalized in {"年"}:
        return max(1, int(round(value * 365.25)))
    return None


def _parse_float_text(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _infer_horizon_from_claim_text(
    claim_text: str,
    publish_date: str,
) -> dict[str, Any]:
    text = str(claim_text or "")
    relative_patterns = (
        r"未来\s*(?P<value>\d+(?:\.\d+)?)\s*(?:个)?(?P<unit>交易日|天|日|周|个月|月|年)(?:内|以内|左右|附近)?",
        r"(?P<value>\d+(?:\.\d+)?)\s*(?:个)?(?P<unit>交易日|天|日|周|个月|月|年)(?:内|以内)",
    )
    for pattern in relative_patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        value = _parse_float_text(match.group("value"))
        if value is None:
            continue
        days = _duration_to_days(value, match.group("unit"))
        if days is None:
            continue
        return {
            "max_days": days,
            "unit": "calendar_day",
            "source": "explicit_claim_text",
            "source_text": match.group(0),
        }

    absolute_match = re.search(r"(?:预计|预期|有望|计划|将)?\s*(?:到|至|截至)\s*(20\d{2})\s*年", text)
    if absolute_match:
        try:
            publish_dt = datetime.strptime(str(publish_date or ""), "%Y-%m-%d")
        except ValueError:
            publish_dt = None
        if publish_dt is not None:
            target_year = int(absolute_match.group(1))
            target_dt = datetime(target_year, 12, 31)
            days = (target_dt - publish_dt).days
            if days > 0:
                return {
                    "max_days": days,
                    "unit": "calendar_day",
                    "source": "explicit_claim_text",
                    "source_text": absolute_match.group(0).strip(),
                }
    return {}


def _normalize_or_infer_horizon(
    horizon: Any,
    *,
    claim_text: str,
    publish_date: str,
) -> tuple[dict[str, Any], bool]:
    normalized = _ensure_mapping(horizon)
    if _horizon_bucket(normalized) != "unknown":
        return normalized, False
    inferred = _infer_horizon_from_claim_text(claim_text, publish_date)
    if inferred:
        return inferred, True
    return normalized, False


def _forecast_mapping_gaps(record: Mapping[str, Any]) -> list[str]:
    gaps: list[str] = []
    target = _ensure_mapping(record.get("target"))
    benchmark = _ensure_mapping(record.get("benchmark"))
    horizon = _ensure_mapping(record.get("horizon"))
    direction = _normalize_forecast_direction(record.get("direction"))
    if _target_id(target) == "unknown":
        gaps.append("target")
    if not benchmark:
        gaps.append("benchmark")
    if direction in {"", "unknown", "ambiguous"}:
        gaps.append("direction")
    if _horizon_bucket(horizon) == "unknown":
        gaps.append("horizon")
    return gaps


def _normalize_forecast_claims(
    payload: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    run_id: str,
    model: str,
    report_id: str,
    chunk_span_id: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in _ensure_list(payload.get("forecast_claims")):
        claim = _ensure_mapping(item)
        raw_claim_text = _record_text(claim, "claim_text", "text")
        if not raw_claim_text:
            continue
        claim_text, claim_text_truncated = _bounded_claim_text(raw_claim_text)
        horizon, horizon_inferred = _normalize_or_infer_horizon(
            claim.get("horizon"),
            claim_text=raw_claim_text,
            publish_date=str(row.get("publish_date") or ""),
        )
        record = {
            "forecast_claim_id": _stable_id(
                "FC",
                {
                    "report_id": report_id,
                    "chunk_span_id": chunk_span_id,
                    "claim_text": claim_text,
                },
            ),
            "claim_id": _stable_id(
                "CLAIM",
                {
                    "report_id": report_id,
                    "claim_text": claim_text,
                },
            ),
            "report_id": report_id,
            "source_id": str(row.get("source_id") or ""),
            "source_span_ids": _source_span_ids(claim, chunk_span_id),
            "claim_text": claim_text,
            "claim_provenance": str(claim.get("claim_provenance") or "unknown"),
            "forecast_testability": str(
                claim.get("forecast_testability") or "insufficient_mapping"
            ),
            "forecast_type": str(claim.get("forecast_type") or "unknown"),
            "target": _ensure_mapping(claim.get("target")),
            "benchmark": _ensure_mapping(claim.get("benchmark")),
            "direction": _normalize_forecast_direction(claim.get("direction")),
            "horizon": horizon,
            "signal_datetime": str(row.get("publish_date") or ""),
            "entry_rule": _ensure_mapping(claim.get("entry_rule")),
            "explicitness": str(claim.get("explicitness") or "unknown"),
            "source_conviction": str(claim.get("source_conviction") or "unknown"),
            "metric_proxy_mapping": _ensure_list(claim.get("metric_proxy_mapping")),
            "failure_modes": _normalize_failure_modes(claim.get("failure_modes")),
            "extraction_quality": _ensure_mapping(claim.get("extraction_quality")),
            "extractor": {
                "run_id": run_id,
                "model": model,
                "input_mode": "original_markdown",
            },
        }
        record["extraction_quality"][
            "claim_text_truncated_for_redaction"
        ] = claim_text_truncated
        if record["claim_provenance"] == "source_grounded":
            record["extraction_quality"].setdefault("span_grounded", True)
        if horizon_inferred:
            record["extraction_quality"]["horizon_inferred_from_claim_text"] = True
            record["extraction_quality"]["horizon_inference_source_text"] = horizon.get(
                "source_text",
                "",
            )
        mapping_gaps = _forecast_mapping_gaps(record)
        if mapping_gaps:
            record["forecast_testability"] = "insufficient_mapping"
            record["extraction_quality"]["mapping_gaps"] = mapping_gaps
            record["extraction_quality"]["needs_human_review"] = True
        records.append(record)
    return records


def _refresh_forecast_mapping_governance(
    forecast_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    refreshed_rows: list[dict[str, Any]] = []
    for row in forecast_rows:
        refreshed = dict(row)
        horizon, horizon_inferred = _normalize_or_infer_horizon(
            refreshed.get("horizon"),
            claim_text=str(refreshed.get("claim_text") or ""),
            publish_date=str(
                refreshed.get("signal_datetime")
                or refreshed.get("publish_date")
                or "",
            ),
        )
        refreshed["horizon"] = horizon
        extraction_quality = dict(_ensure_mapping(refreshed.get("extraction_quality")))
        if horizon_inferred:
            extraction_quality["horizon_inferred_from_claim_text"] = True
            extraction_quality["horizon_inference_source_text"] = horizon.get(
                "source_text",
                "",
            )
        mapping_gaps = _forecast_mapping_gaps(refreshed)
        if mapping_gaps:
            refreshed["forecast_testability"] = "insufficient_mapping"
            extraction_quality["mapping_gaps"] = mapping_gaps
            extraction_quality["needs_human_review"] = True
        else:
            extraction_quality.pop("mapping_gaps", None)
            if refreshed.get("forecast_testability") == "insufficient_mapping":
                refreshed["forecast_testability"] = "testable"
                extraction_quality["needs_human_review"] = False
        refreshed["extraction_quality"] = extraction_quality
        refreshed_rows.append(refreshed)
    return refreshed_rows


def _refresh_analytical_footprint_indicator_governance(
    footprint_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    refreshed_rows: list[dict[str, Any]] = []
    for row in footprint_rows:
        refreshed = dict(row)
        refreshed["indicator_mentions"] = _normalize_indicator_mentions(
            refreshed.get("indicator_mentions")
        )
        refreshed_rows.append(refreshed)
    return refreshed_rows


def _normalize_footprints(
    payload: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    run_id: str,
    model: str,
    report_id: str,
    chunk_span_id: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in _ensure_list(payload.get("analytical_footprints")):
        footprint = _ensure_mapping(item)
        topic = _record_text(footprint, "topic", "name") or "unknown"
        target_agents, target_entities = _split_agent_and_entity_candidates(
            footprint.get("target_agent_candidates")
        )
        record = {
            "footprint_id": _stable_id(
                "AFP",
                {
                    "report_id": report_id,
                    "chunk_span_id": chunk_span_id,
                    "topic": topic,
                    "indicator_mentions": footprint.get("indicator_mentions"),
                },
            ),
            "report_id": report_id,
            "source_id": str(row.get("source_id") or ""),
            "source_span_ids": _source_span_ids(footprint, chunk_span_id),
            "extraction_type": str(footprint.get("extraction_type") or "mixed"),
            "market": "CN_A_SHARE",
            "sector": str(row.get("industry") or row.get("query_key") or "unknown"),
            "topic": topic,
            "indicator_mentions": _normalize_indicator_mentions(
                footprint.get("indicator_mentions")
            ),
            "analysis_patterns": _ensure_list(footprint.get("analysis_patterns")),
            "target_agent_candidates": target_agents,
            "target_entity_candidates": target_entities,
            "license_class": "operator_approved_internal_research_use",
            "storage_policy": "derived_metadata_only_full_text_cached_locally",
            "extractor": {
                "run_id": run_id,
                "model": model,
                "input_mode": "original_markdown",
            },
        }
        records.append(record)
    return records


def _bounded_metadata_text(value: Any, *, max_chars: int = MAX_STORED_CLAIM_TEXT_CHARS) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."


def _footprint_review_target_hash(row: Mapping[str, Any]) -> str:
    payload = {
        "footprint_id": row.get("footprint_id"),
        "report_id": row.get("report_id"),
        "source_id": row.get("source_id"),
        "source_span_ids": _ensure_list(row.get("source_span_ids")),
        "extraction_type": row.get("extraction_type"),
        "topic": row.get("topic"),
        "indicator_mentions": row.get("indicator_mentions"),
        "analysis_patterns": row.get("analysis_patterns"),
    }
    encoded = json.dumps(
        _jsonable(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def _indicator_review_preview(mentions: Any) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for mention in _ensure_list(mentions)[:5]:
        mention_map = _ensure_mapping(mention)
        preview.append(
            {
                "indicator_text": _bounded_metadata_text(
                    mention_map.get("indicator_text")
                ),
                "canonical_metric_candidate": _bounded_metadata_text(
                    mention_map.get("canonical_metric_candidate")
                ),
                "data_source_mentioned": _bounded_metadata_text(
                    mention_map.get("data_source_mentioned")
                ),
                "frequency": _bounded_metadata_text(mention_map.get("frequency")),
                "transformation": _bounded_metadata_text(
                    mention_map.get("transformation")
                ),
                "source_grounded": bool(mention_map.get("source_grounded")),
            }
        )
    return preview


def _analysis_pattern_review_preview(patterns: Any) -> list[str]:
    out: list[str] = []
    for pattern in _ensure_list(patterns)[:5]:
        if isinstance(pattern, Mapping):
            text = _record_text(pattern, "pattern_candidate", "name", "description")
            if not text:
                text = json.dumps(_jsonable(pattern), ensure_ascii=False, sort_keys=True)
        else:
            text = str(pattern or "")
        out.append(_bounded_metadata_text(text))
    return out


def _existing_footprint_review_rows(path: Path) -> dict[str, Mapping[str, Any]]:
    if not path.exists():
        return {}
    rows, _ = load_jsonl_with_errors(path, label="analytical footprint review")
    return {
        str(row.get("footprint_id") or ""): row
        for row in rows
        if isinstance(row, Mapping) and str(row.get("footprint_id") or "").strip()
    }


def _footprint_review_template_row(
    row: Mapping[str, Any],
    *,
    existing_row: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    target_hash = _footprint_review_target_hash(row)
    review_row = {
        "review_kind": "analytical_footprint_gold_set",
        "footprint_id": str(row.get("footprint_id") or ""),
        "report_id": str(row.get("report_id") or ""),
        "source_id": str(row.get("source_id") or ""),
        "source_span_ids": _ensure_list(row.get("source_span_ids")),
        "target_row_hash": target_hash,
        "target_review_path": ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
        "review_context_ref": "registry/report_intelligence/analytical_footprints.jsonl",
        "manual_review_required": True,
        "topic_preview": _bounded_metadata_text(row.get("topic")),
        "extraction_type": str(row.get("extraction_type") or "unknown"),
        "sector": str(row.get("sector") or "unknown"),
        "indicator_mentions_review_preview": _indicator_review_preview(
            row.get("indicator_mentions")
        ),
        "analysis_patterns_review_preview": _analysis_pattern_review_preview(
            row.get("analysis_patterns")
        ),
        "target_agent_candidates": _ensure_list(row.get("target_agent_candidates")),
        "target_entity_candidates": _ensure_list(row.get("target_entity_candidates")),
        "footprint_correct": None,
        "source_span_supports_footprint": None,
        "metric_mapping_correct": None,
        "inferred_steps_tagged_correctly": None,
        "unknowns_used_when_uncertain": None,
        "no_proprietary_text_leakage": None,
        "manual_error_tags": [],
        "reviewer": "",
        "review_date": "",
        "review_notes": "",
    }
    if (
        existing_row
        and existing_row.get("target_row_hash") == target_hash
        and str(existing_row.get("review_kind") or "")
        == "analytical_footprint_gold_set"
    ):
        for field in (
            *ANALYTICAL_FOOTPRINT_REVIEW_REQUIRED_FIELDS,
            "manual_error_tags",
        ):
            if field in existing_row:
                review_row[field] = existing_row[field]
    return review_row


def build_analytical_footprint_review_rows(
    footprint_rows: Sequence[Mapping[str, Any]],
    *,
    existing_template_path: Path | None = None,
) -> list[dict[str, Any]]:
    existing_rows = (
        _existing_footprint_review_rows(existing_template_path)
        if existing_template_path is not None
        else {}
    )
    return [
        _footprint_review_template_row(
            row,
            existing_row=existing_rows.get(str(row.get("footprint_id") or "")),
        )
        for row in footprint_rows
        if str(row.get("footprint_id") or "").strip()
    ]


def _footprint_review_row_complete(row: Mapping[str, Any]) -> bool:
    if not str(row.get("reviewer") or "").strip():
        return False
    if not str(row.get("review_date") or "").strip():
        return False
    if not str(row.get("review_notes") or "").strip():
        return False
    return all(
        isinstance(row.get(field), bool)
        for field in ANALYTICAL_FOOTPRINT_REVIEW_BOOLEAN_FIELDS
    )


def build_analytical_footprint_review_summary(
    review_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    complete_rows = [row for row in review_rows if _footprint_review_row_complete(row)]
    pending_rows = len(review_rows) - len(complete_rows)

    def rate(field: str) -> float | None:
        if not complete_rows:
            return None
        return round(
            sum(1 for row in complete_rows if row.get(field) is True)
            / len(complete_rows),
            6,
        )

    error_counts: dict[str, int] = {}
    for row in complete_rows:
        for tag in _ensure_list(row.get("manual_error_tags")):
            tag_text = str(tag or "").strip()
            if tag_text:
                error_counts[tag_text] = error_counts.get(tag_text, 0) + 1
    blockers: list[str] = []
    if not review_rows:
        blockers.append("analytical footprint review template has no rows")
    if pending_rows:
        blockers.append(
            f"{pending_rows} analytical footprint review rows still pending"
        )
    precision_recall_report = {
        "footprint_precision": rate("footprint_correct"),
        "span_support_precision": rate("source_span_supports_footprint"),
        "metric_mapping_accuracy": rate("metric_mapping_correct"),
        "inferred_step_tagging_accuracy": rate(
            "inferred_steps_tagged_correctly"
        ),
        "unknown_on_ambiguity_rate": rate("unknowns_used_when_uncertain"),
        "proprietary_leakage_free_rate": rate(
            "no_proprietary_text_leakage"
        ),
        "recall_estimate": None,
        "recall_status": "requires_human_negative_examples",
    }
    quality_gate_blockers: list[str] = []
    for field, threshold in ANALYTICAL_FOOTPRINT_REVIEW_QUALITY_THRESHOLDS.items():
        value = precision_recall_report.get(field)
        if value is None:
            quality_gate_blockers.append(f"{field} unavailable")
        elif float(value) < threshold:
            quality_gate_blockers.append(
                f"{field} {value:.6f} below threshold {threshold:.2f}"
            )
    review_complete = bool(review_rows) and pending_rows == 0
    quality_gate_passed = review_complete and not quality_gate_blockers
    return {
        "summary_id": "RKE-REPORT-INTELLIGENCE-FOOTPRINT-REVIEW-SUMMARY",
        "review_kind": "analytical_footprint_gold_set",
        "accepted": quality_gate_passed,
        "review_complete": review_complete,
        "quality_gate_passed": quality_gate_passed,
        "quality_gate_thresholds": dict(
            sorted(ANALYTICAL_FOOTPRINT_REVIEW_QUALITY_THRESHOLDS.items())
        ),
        "quality_gate_blockers": quality_gate_blockers,
        "manual_review_required": True,
        "review_template_path": ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
        "error_taxonomy_path": ANALYTICAL_FOOTPRINT_ERROR_TAXONOMY_PATH,
        "total_rows": len(review_rows),
        "complete_rows": len(complete_rows),
        "pending_rows": pending_rows,
        "precision_recall_report": precision_recall_report,
        "error_counts": dict(sorted(error_counts.items())),
        "blockers": [*blockers, *quality_gate_blockers],
        "policy": (
            "analytical footprint review is a manual gold-set gate for source "
            "grounding, metric mapping, inferred-step tagging, ambiguity handling, "
            "and proprietary text leakage; no rows are accepted until reviewers fill "
            "all required fields and quality thresholds pass"
        ),
    }


def build_analytical_footprint_error_taxonomy() -> dict[str, Any]:
    return {
        "taxonomy_id": "RKE-REPORT-INTELLIGENCE-FOOTPRINT-ERROR-TAXONOMY",
        "review_kind": "analytical_footprint_gold_set",
        "required_manual_fields": list(
            ANALYTICAL_FOOTPRINT_REVIEW_REQUIRED_FIELDS
        )
        + ["manual_error_tags"],
        "error_tags": [
            {
                "tag": "unsupported_footprint",
                "description": "The extracted topic or method is not supported by the cited span.",
            },
            {
                "tag": "metric_mapping_error",
                "description": "The canonical metric, unit, source, frequency, or transformation is wrong.",
            },
            {
                "tag": "hallucinated_metric",
                "description": "The extractor invented a metric not present in the report or cited span.",
            },
            {
                "tag": "inferred_step_mislabeled_source_grounded",
                "description": "A derived or LLM-inferred step was stored as source-grounded.",
            },
            {
                "tag": "ambiguous_metric_not_unknown",
                "description": "An uncertain metric/source/window should have been marked unknown.",
            },
            {
                "tag": "proprietary_text_leakage",
                "description": "The review row includes long proprietary report text instead of metadata.",
            },
        ],
    }


def write_analytical_footprint_review_artifacts(
    registry_dir: Path,
    footprint_rows: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    template_path = registry_dir / "analytical_footprint_review_template.jsonl"
    review_rows = build_analytical_footprint_review_rows(
        footprint_rows,
        existing_template_path=template_path,
    )
    summary = build_analytical_footprint_review_summary(review_rows)
    taxonomy = build_analytical_footprint_error_taxonomy()
    return {
        "analytical_footprint_review_template": str(
            _write_jsonl(template_path, review_rows)["path"]
        ),
        "analytical_footprint_review_summary": str(
            _write_json(
                registry_dir / "analytical_footprint_review_summary.json",
                summary,
            )["path"]
        ),
        "analytical_footprint_error_taxonomy": str(
            _write_json(
                registry_dir / "analytical_footprint_error_taxonomy.json",
                taxonomy,
            )["path"]
        ),
    }


def _split_mapping_rows(rows: Sequence[Any]) -> tuple[list[Mapping[str, Any]], tuple[int, ...]]:
    valid_rows: list[Mapping[str, Any]] = []
    invalid_row_numbers: list[int] = []
    for index, row in enumerate(rows, 1):
        if isinstance(row, Mapping):
            valid_rows.append(row)
        else:
            invalid_row_numbers.append(index)
    return valid_rows, tuple(invalid_row_numbers)


def _duplicate_ids(ids: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for row_id in ids:
        if row_id in seen:
            duplicates.add(row_id)
        seen.add(row_id)
    return tuple(sorted(duplicates))


def _required_review_string_failures(row: Mapping[str, Any], field: str) -> list[str]:
    value = row.get(field)
    if value is None or value == "":
        return [f"{field} required"]
    if not isinstance(value, str):
        return [f"{field} must be string"]
    if not value.strip():
        return [f"{field} required"]
    return []


def _optional_review_string_failures(row: Mapping[str, Any], field: str) -> list[str]:
    value = row.get(field)
    if value is None:
        return []
    if not isinstance(value, str):
        return [f"{field} must be string"]
    return []


def _review_date_failures(row: Mapping[str, Any], field: str) -> list[str]:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return [f"{field} must be YYYY-MM-DD"]
    if parsed.isoformat() != value:
        return [f"{field} must be YYYY-MM-DD"]
    return []


def _footprint_review_import_allowed_fields(
    target_rows: Sequence[Mapping[str, Any]],
) -> frozenset[str]:
    allowed: set[str] = set()
    for row in target_rows:
        allowed.update(str(field) for field in row)
    allowed.update(ANALYTICAL_FOOTPRINT_REVIEW_REQUIRED_FIELDS)
    allowed.add("manual_error_tags")
    return frozenset(allowed)


def _footprint_review_import_unexpected_fields(
    row: Mapping[str, Any],
    allowed_fields: frozenset[str],
) -> tuple[str, ...]:
    return tuple(sorted(str(field) for field in set(row) - allowed_fields))


def _footprint_review_import_row_failures(
    row: Mapping[str, Any],
    *,
    target_row: Mapping[str, Any] | None,
    duplicate_ids: Sequence[str],
    missing_target_ids: Sequence[str],
    allowed_fields: frozenset[str],
) -> list[str]:
    failures: list[str] = []
    failures.extend(_required_review_string_failures(row, "footprint_id"))
    footprint_id = str(row.get("footprint_id") or "").strip()
    if footprint_id in set(duplicate_ids):
        failures.append("duplicate footprint_id in import")
    if footprint_id in set(missing_target_ids):
        failures.append("footprint_id missing from target review template")
    for field in _footprint_review_import_unexpected_fields(row, allowed_fields):
        failures.append(f"{field} unexpected in analytical footprint review import")
    for field in manual_review_forbidden_field_paths(row):
        failures.append(f"{field} forbidden in analytical footprint review import")
    failures.extend(_required_review_string_failures(row, "target_row_hash"))
    failures.extend(_required_review_string_failures(row, "target_review_path"))
    failures.extend(_required_review_string_failures(row, "review_context_ref"))
    if str(row.get("target_review_path") or "").strip() != ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH:
        failures.append(
            f"target_review_path must match {ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH}"
        )
    if str(row.get("review_context_ref") or "").strip() != "registry/report_intelligence/analytical_footprints.jsonl":
        failures.append(
            "review_context_ref must match registry/report_intelligence/analytical_footprints.jsonl"
        )
    if target_row is not None:
        expected_hash = str(target_row.get("target_row_hash") or "").strip()
        actual_hash = str(row.get("target_row_hash") or "").strip()
        if actual_hash and expected_hash and actual_hash != expected_hash:
            failures.append("target_row_hash does not match target review row")
    for field in ANALYTICAL_FOOTPRINT_REVIEW_BOOLEAN_FIELDS:
        if not isinstance(row.get(field), bool):
            failures.append(f"{field} must be boolean")
    for field in ("reviewer", "review_date", "review_notes"):
        failures.extend(_required_review_string_failures(row, field))
    failures.extend(_review_date_failures(row, "review_date"))
    failures.extend(_optional_review_string_failures(row, "review_notes"))
    manual_error_tags = row.get("manual_error_tags")
    if manual_error_tags is not None:
        if not isinstance(manual_error_tags, list):
            failures.append("manual_error_tags must be list")
        else:
            for index, tag in enumerate(manual_error_tags):
                if not isinstance(tag, str):
                    failures.append(f"manual_error_tags[{index}] must be string")
    return failures


def apply_analytical_footprint_review_import(
    root: str | Path,
    input_path: str | Path,
    *,
    dry_run: bool = False,
) -> AnalyticalFootprintReviewImportReport:
    root_path = Path(root)
    resolved_input_path = Path(input_path)
    if not resolved_input_path.is_absolute():
        resolved_input_path = root_path / resolved_input_path
    target_path = root_path / ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH
    summary_path = root_path / ANALYTICAL_FOOTPRINT_REVIEW_SUMMARY_PATH
    report_path = root_path / ANALYTICAL_FOOTPRINT_REVIEW_IMPORT_REPORT_PATH
    input_rows_raw, input_parse_blockers = load_jsonl_with_errors(
        resolved_input_path,
        label="analytical footprint review import",
    )
    target_rows_raw, target_parse_blockers = load_jsonl_with_errors(
        target_path,
        label="analytical footprint target review",
    )
    input_rows, invalid_input_rows = _split_mapping_rows(input_rows_raw)
    target_rows, invalid_target_rows = _split_mapping_rows(target_rows_raw)
    target_by_id = {
        str(row.get("footprint_id") or ""): row
        for row in target_rows
        if str(row.get("footprint_id") or "").strip()
    }
    input_ids = [
        str(row.get("footprint_id") or "").strip()
        for row in input_rows
        if str(row.get("footprint_id") or "").strip()
    ]
    duplicate_ids = _duplicate_ids(input_ids)
    missing_target_ids = tuple(
        sorted(row_id for row_id in set(input_ids) if row_id not in target_by_id)
    )
    allowed_fields = _footprint_review_import_allowed_fields(target_rows)
    invalid_rows: list[AnalyticalFootprintReviewImportInvalidRow] = []
    for index, raw_row in enumerate(input_rows_raw, 1):
        if not isinstance(raw_row, Mapping):
            invalid_rows.append(
                AnalyticalFootprintReviewImportInvalidRow(
                    row_number=index,
                    row_id=f"<non-object-row-{index}>",
                    reasons=("review row must be object",),
                )
            )
            continue
        row_id = str(raw_row.get("footprint_id") or "").strip()
        failures = _footprint_review_import_row_failures(
            raw_row,
            target_row=target_by_id.get(row_id),
            duplicate_ids=duplicate_ids,
            missing_target_ids=missing_target_ids,
            allowed_fields=allowed_fields,
        )
        if failures:
            invalid_rows.append(
                AnalyticalFootprintReviewImportInvalidRow(
                    row_number=index,
                    row_id=row_id or "<missing-footprint-id>",
                    reasons=tuple(failures),
                )
            )

    blockers: list[str] = []
    if not input_rows_raw:
        blockers.append("analytical footprint review import file is empty")
    if invalid_input_rows:
        blockers.append(
            "analytical footprint review import row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in invalid_input_rows)
        )
    if invalid_target_rows:
        blockers.append(
            "analytical footprint target review row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in invalid_target_rows)
        )
    if duplicate_ids:
        blockers.append(f"{len(duplicate_ids)} duplicate footprint ids")
    if missing_target_ids:
        blockers.append(f"{len(missing_target_ids)} footprint ids are missing from target")
    if invalid_rows:
        blockers.append(f"{len(invalid_rows)} analytical footprint review rows failed validation")
    blockers.extend(input_parse_blockers)
    blockers.extend(target_parse_blockers)
    accepted = not blockers

    applied_rows = 0
    if accepted and not dry_run:
        import_by_id = {str(row.get("footprint_id") or ""): row for row in input_rows}
        merged: list[dict[str, Any]] = []
        for target_row in target_rows:
            row = dict(target_row)
            imported = import_by_id.get(str(row.get("footprint_id") or ""))
            if imported is not None:
                for field in (
                    *ANALYTICAL_FOOTPRINT_REVIEW_REQUIRED_FIELDS,
                    "manual_error_tags",
                ):
                    if field in imported:
                        row[field] = imported[field]
                applied_rows += 1
            merged.append(row)
        _write_jsonl(target_path, merged)
        _write_json(summary_path, build_analytical_footprint_review_summary(merged))

    report = AnalyticalFootprintReviewImportReport(
        report_id="RKE-REPORT-INTELLIGENCE-FOOTPRINT-REVIEW-IMPORT-REPORT",
        input_path=str(resolved_input_path),
        target_path=ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
        dry_run=dry_run,
        accepted=accepted,
        input_rows=len(input_rows_raw),
        applied_rows=applied_rows,
        rejected_rows=len(invalid_rows),
        duplicate_ids=duplicate_ids,
        missing_target_ids=missing_target_ids,
        invalid_rows=tuple(invalid_rows),
        summary_path=ANALYTICAL_FOOTPRINT_REVIEW_SUMMARY_PATH,
        blockers=tuple(blockers),
    )
    _write_json(report_path, asdict(report))
    return report


def _canonical_metric_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    lowered = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "_", lowered)
    lowered = re.sub(r"_+", "_", lowered).strip("_")
    return lowered[:120]


def _normalize_metric_candidates(
    payload: Mapping[str, Any],
    footprints: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    model: str,
) -> list[dict[str, Any]]:
    raw_metrics = [_ensure_mapping(item) for item in _ensure_list(payload.get("metric_candidates"))]
    for footprint in footprints:
        for mention in _ensure_list(footprint.get("indicator_mentions")):
            mention_map = _ensure_mapping(mention)
            canonical = _record_text(
                mention_map,
                "canonical_metric_candidate",
                "canonical_name",
                "indicator_text",
            )
            if canonical:
                raw_metrics.append(
                    {
                        "canonical_name": canonical,
                        "aliases": [mention_map.get("indicator_text") or canonical],
                        "metric_family": mention_map.get("role_in_argument")
                        or mention_map.get("metric_family")
                        or "unknown",
                        "raw_data_requirements": [
                            {
                                "raw_source": mention_map.get("data_source_mentioned")
                                or "unknown",
                                "frequency": mention_map.get("frequency") or "unknown",
                                "pit_required": True,
                            }
                        ],
                        "default_transformation": {
                            "type": mention_map.get("transformation") or "unknown",
                            "window": mention_map.get("lookback_window") or {},
                        },
                        "target_agents": footprint.get("target_agent_candidates")
                        or [],
                    }
                )
    deduped: dict[str, dict[str, Any]] = {}
    for item in raw_metrics:
        canonical = _canonical_metric_name(
            item.get("canonical_name")
            or item.get("metric_name")
            or item.get("name")
        )
        if not canonical:
            continue
        existing = deduped.setdefault(
            canonical,
            {
                "metric_candidate_id": _stable_id(
                    "METRIC",
                    {"canonical_name": canonical},
                ),
                "canonical_name": canonical,
                "aliases": [],
                "metric_family": str(item.get("metric_family") or "unknown"),
                "market": "CN_A_SHARE",
                "raw_data_requirements": [],
                "default_transformation": _ensure_mapping(
                    item.get("default_transformation")
                ),
                "mentioned_by": {
                    "report_count": 0,
                    "high_weight_report_count": 0,
                    "source_weighted_count": 0,
                },
                "target_agents": [],
                "current_tool_coverage": "unknown",
                "existing_tool_ids": [],
                "priority_bucket": "candidate",
                "status": "candidate_metric",
                "extractor": {"run_id": run_id, "model": model},
            },
        )
        aliases = [
            str(alias)
            for alias in _ensure_list(item.get("aliases"))
            if str(alias).strip()
        ]
        if not aliases and item.get("canonical_name"):
            aliases = [str(item["canonical_name"])]
        existing["aliases"] = list(dict.fromkeys([*existing["aliases"], *aliases]))
        existing["raw_data_requirements"] = [
            *existing["raw_data_requirements"],
            *_ensure_list(item.get("raw_data_requirements")),
        ]
        target_agents, _ = _split_agent_and_entity_candidates(item.get("target_agents"))
        existing["target_agents"] = list(
            dict.fromkeys(
                [
                    *existing["target_agents"],
                    *target_agents,
                ]
            )
        )
        existing["mentioned_by"]["report_count"] += 1
    records = list(deduped.values())
    for record in records:
        coverage = classify_tool_coverage(str(record["canonical_name"]))
        record["current_tool_coverage"] = coverage["coverage_status"]
        record["existing_tool_ids"] = coverage["existing_tool_ids"]
    return records


def _normalize_method_patterns(
    payload: Mapping[str, Any],
    footprints: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    model: str,
) -> list[dict[str, Any]]:
    raw_methods = [_ensure_mapping(item) for item in _ensure_list(payload.get("method_patterns"))]
    for footprint in footprints:
        for pattern in _ensure_list(footprint.get("analysis_patterns")):
            pattern_map = _ensure_mapping(pattern)
            name = _record_text(pattern_map, "pattern_candidate", "name")
            if name:
                raw_methods.append(
                    {
                        "name": name,
                        "steps": pattern_map.get("steps") or [],
                        "required_current_data": pattern_map.get(
                            "required_current_data"
                        )
                        or [],
                        "optional_confirmation_data": pattern_map.get(
                            "optional_confirmation_data"
                        )
                        or [],
                        "failure_modes": pattern_map.get("failure_modes") or [],
                        "target_agents": footprint.get("target_agent_candidates")
                        or [],
                    }
                )
    deduped: dict[str, dict[str, Any]] = {}
    for item in raw_methods:
        name = _record_text(item, "name", "pattern_candidate")
        if not name:
            continue
        key = _canonical_metric_name(name)
        existing = deduped.setdefault(
            key,
            {
                "method_pattern_id": _stable_id("METHOD", {"name": name}),
                "name": name,
                "description": str(item.get("description") or ""),
                "source_footprint_ids": [],
                "steps": [],
                "required_current_data": [],
                "optional_confirmation_data": [],
                "failure_modes": [],
                "target_agents": [],
                "validation_status": "candidate",
                "allowed_runtime_mode": "shadow_only",
                "extractor": {"run_id": run_id, "model": model},
            },
        )
        for field in (
            "source_footprint_ids",
            "steps",
            "required_current_data",
            "optional_confirmation_data",
            "failure_modes",
            "target_agents",
        ):
            additions = _ensure_list(item.get(field))
            if field == "target_agents":
                additions, _ = _split_agent_and_entity_candidates(additions)
            existing[field] = _merge_unique_values(
                existing[field],
                additions,
            )
    return list(deduped.values())


def classify_tool_coverage(canonical_name: str) -> dict[str, Any]:
    name = canonical_name.lower()
    checks = (
        (
            ("pboc", "omo", "公开市场", "逆回购", "央行"),
            "exact_match",
            ("tool.get_pboc_ops",),
        ),
        (
            ("policy_uncertainty", "epu", "政策不确定性"),
            "exact_match",
            ("tool.get_policy_uncertainty_index",),
        ),
        (
            ("realized_volatility", "rk_th2", "波动率"),
            "exact_match",
            ("tool.get_realized_volatility",),
        ),
        (
            ("dr007", "r007", "repo", "回购", "资金利率"),
            "partial_match",
            ("tool.get_money_market_rate_proxy",),
        ),
        (
            ("northbound", "北向", "陆股通"),
            "partial_match",
            ("tool.get_cross_border_flow_proxy",),
        ),
    )
    for keywords, status, tool_ids in checks:
        if any(keyword in name for keyword in keywords):
            return {"coverage_status": status, "existing_tool_ids": list(tool_ids)}
    return {"coverage_status": "missing", "existing_tool_ids": []}


def _is_gap_missing_or_data_blocked(gap_type: str) -> bool:
    normalized = gap_type.lower().replace(" ", "_")
    return any(
        token in normalized
        for token in (
            "missing_metric",
            "partial_metric_coverage",
            "data_availability",
            "data_source",
            "data_granularity",
            "market_data",
            "no_pit",
        )
    )


def _tool_gap_priority_metadata(
    *,
    gap_type: str,
    metric_name: str,
    method_name: str,
    target_agents: Sequence[str],
    priority_reasons: Sequence[Any],
    blocking_issues: Sequence[Any],
) -> tuple[str, list[str], list[str]]:
    reasons = [str(item) for item in priority_reasons if str(item).strip()]
    issues = [str(item) for item in blocking_issues if str(item).strip()]
    has_agent = any(str(agent).strip() for agent in target_agents)
    has_method_support = bool(method_name.strip())
    missing_or_blocked = _is_gap_missing_or_data_blocked(gap_type)
    if missing_or_blocked and has_agent and (issues or reasons):
        bucket = "high"
        reasons.append("missing_or_partial_data_blocks_named_agent")
    elif missing_or_blocked and (has_method_support or issues or reasons):
        bucket = "medium"
        reasons.append("missing_or_partial_data_blocks_extracted_method")
    elif has_agent and (issues or reasons):
        bucket = "medium"
        reasons.append("tool_gap_has_named_agent_support")
    else:
        bucket = "low"
        reasons.append("insufficient_agent_or_method_support_for_prioritization")
    if bucket in {"high", "medium"} and not issues:
        issues.append("requires_engineering_review")
    if metric_name and not any("metric" in reason.lower() for reason in reasons):
        reasons.append("metric_candidate_extracted_from_original_report")
    return bucket, list(dict.fromkeys(reasons)), list(dict.fromkeys(issues))


def _normalize_tool_gaps(
    payload: Mapping[str, Any],
    metrics: Sequence[Mapping[str, Any]],
    methods: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    model: str,
) -> list[dict[str, Any]]:
    raw_gaps = [_ensure_mapping(item) for item in _ensure_list(payload.get("tool_gaps"))]
    method_names = [
        str(method.get("name") or "")
        for method in methods
        if str(method.get("name") or "").strip()
    ]
    for metric in metrics:
        coverage = str(metric.get("current_tool_coverage") or "unknown")
        if coverage in {"missing", "partial_match", "proxy_available", "no_pit_history"}:
            raw_gaps.append(
                {
                    "gap_type": "missing_metric"
                    if coverage == "missing"
                    else "partial_metric_coverage",
                    "metric_name": metric.get("canonical_name"),
                    "method_name": method_names[0] if method_names else "",
                    "target_agents": metric.get("target_agents") or [],
                    "priority_reasons": [
                        f"tool coverage is {coverage} for extracted metric"
                    ],
                    "blocking_issues": ["requires_engineering_review"],
                }
            )
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_gaps:
        metric_name = _record_text(item, "metric_name", "metric_candidate_id")
        method_name = _record_text(item, "method_name", "method_pattern_id")
        gap_type = str(item.get("gap_type") or "unknown")
        key = "|".join((gap_type, metric_name, method_name))
        if key in seen or not (metric_name or method_name):
            continue
        seen.add(key)
        target_agents, _target_entities = _split_agent_and_entity_candidates(
            item.get("target_agents")
        )
        priority_bucket, priority_reasons, blocking_issues = _tool_gap_priority_metadata(
            gap_type=gap_type,
            metric_name=metric_name,
            method_name=method_name,
            target_agents=target_agents,
            priority_reasons=_ensure_list(item.get("priority_reasons")),
            blocking_issues=_ensure_list(item.get("blocking_issues")),
        )
        records.append(
            {
                "tool_gap_id": _stable_id(
                    "TG",
                    {
                        "gap_type": gap_type,
                        "metric_name": metric_name,
                        "method_name": method_name,
                    },
                ),
                "gap_type": gap_type,
                "metric_candidate_id": _stable_id(
                    "METRIC",
                    {"canonical_name": _canonical_metric_name(metric_name)},
                )
                if metric_name
                else "",
                "metric_name": metric_name,
                "method_pattern_ids": [
                    _stable_id("METHOD", {"name": method_name})
                ]
                if method_name
                else [],
                "method_name": method_name,
                "target_agents": target_agents,
                "research_origin": {
                    "source_footprint_ids": _ensure_list(
                        item.get("source_footprint_ids")
                    ),
                    "source_weighted_support": "unknown",
                },
                "priority_bucket": priority_bucket,
                "priority_reasons": priority_reasons,
                "blocking_issues": blocking_issues,
                "owner": str(item.get("owner") or "data_engineering"),
                "status": str(item.get("status") or "proposal_pending"),
                "extractor": {"run_id": run_id, "model": model},
            }
        )
    return records


def _refresh_tool_gap_governance(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    governed_rows: list[dict[str, Any]] = []
    for row in rows:
        metric_name = str(row.get("metric_name") or row.get("metric_candidate_id") or "")
        method_name = str(row.get("method_name") or "")
        target_agents, _target_entities = _split_agent_and_entity_candidates(
            row.get("target_agents")
        )
        priority_bucket, priority_reasons, blocking_issues = _tool_gap_priority_metadata(
            gap_type=str(row.get("gap_type") or "unknown"),
            metric_name=metric_name,
            method_name=method_name,
            target_agents=target_agents,
            priority_reasons=_ensure_list(row.get("priority_reasons")),
            blocking_issues=_ensure_list(row.get("blocking_issues")),
        )
        governed = dict(row)
        governed.update(
            {
                "target_agents": target_agents,
                "priority_bucket": priority_bucket,
                "priority_reasons": priority_reasons,
                "blocking_issues": blocking_issues,
                "owner": str(row.get("owner") or "data_engineering"),
                "status": str(row.get("status") or "proposal_pending"),
            }
        )
        governed_rows.append(governed)
    return governed_rows


def _backfill_tool_gaps_from_metric_candidates(
    tool_gap_rows: Sequence[Mapping[str, Any]],
    metric_rows: Sequence[Mapping[str, Any]],
    method_rows: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    model: str,
) -> list[dict[str, Any]]:
    records = [dict(row) for row in tool_gap_rows]
    _append_unique_records(
        records,
        _normalize_tool_gaps(
            {},
            metric_rows,
            method_rows,
            run_id=run_id,
            model=model,
        ),
        key="tool_gap_id",
    )
    return _refresh_tool_gap_governance(records)


def _backfill_metric_candidates_from_tool_gaps(
    metric_rows: Sequence[Mapping[str, Any]],
    tool_gap_rows: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
) -> list[dict[str, Any]]:
    records = [dict(row) for row in metric_rows]
    existing_ids = {
        str(row.get("metric_candidate_id") or "")
        for row in records
        if str(row.get("metric_candidate_id") or "").strip()
    }
    for gap in tool_gap_rows:
        metric_id = str(gap.get("metric_candidate_id") or "").strip()
        if not metric_id or metric_id in existing_ids:
            continue
        metric_name = str(gap.get("metric_name") or metric_id)
        records.append(
            {
                "metric_candidate_id": metric_id,
                "canonical_name": metric_name,
                "aliases": [],
                "metric_family": _canonical_metric_name(metric_name)
                or "tool_gap_backfill",
                "market": "CN_A_SHARE",
                "raw_data_requirements": ["unknown_raw_data_source"],
                "default_transformation": {},
                "mentioned_by": {
                    "report_count": 0,
                    "high_weight_report_count": 0,
                    "source_weighted_count": 0,
                },
                "target_agents": _ensure_list(gap.get("target_agents")),
                "current_tool_coverage": "missing",
                "existing_tool_ids": [],
                "priority_bucket": "low",
                "status": "backfilled_from_tool_gap",
                "backfill_source": {
                    "tool_gap_id": gap.get("tool_gap_id") or "",
                    "run_id": run_id,
                    "policy": "preserve_tool_gap_metric_lineage_without_promotion",
                },
            }
        )
        existing_ids.add(metric_id)
    return records


def _horizon_bucket(horizon: Mapping[str, Any]) -> str:
    preferred = horizon.get("preferred_days") or horizon.get("max_days") or horizon.get("min_days")
    try:
        days = int(preferred)
    except (TypeError, ValueError):
        return "unknown"
    if days <= 5:
        return "5d"
    if days <= 20:
        return "20d"
    if days <= 60:
        return "60d"
    return "long_horizon"


def _horizon_preferred_days(horizon: Mapping[str, Any]) -> int | None:
    for key in ("preferred_days", "max_days", "min_days"):
        try:
            return int(horizon[key])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _target_id(target: Mapping[str, Any]) -> str:
    return str(target.get("target_id") or target.get("target_name") or "unknown")


STOCK_TARGET_PRICE_VALUE_KEYS = (
    "target_price",
    "price_target",
    "target_price_value",
    "price_target_value",
    "target_price_rmb",
    "target_price_cny",
    "target_price_yuan",
    "target_price_per_share",
)

STOCK_TARGET_PRICE_NUMERIC_KEYS = (
    "value",
    "amount",
    "price",
    "target",
    "target_price",
    "price_target",
)

STOCK_TARGET_PRICE_PROVENANCE_KEYS = (
    "target_price_provenance",
    "price_target_provenance",
    "provenance",
    "source",
    "grounding",
)

STOCK_TARGET_PRICE_HIT_POLICY = (
    "auxiliary_source_grounded_target_price_hit_v1:"
    " positive uses exit_price>=target_price; negative uses exit_price<=target_price;"
    " does not affect directional_hit"
)


def _structured_float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    parsed = _float_or_none(value)
    if parsed is not None:
        return parsed
    if isinstance(value, str):
        matches = re.findall(r"[-+]?\d+(?:\.\d+)?", value.replace(",", ""))
        if len(matches) == 1:
            return _float_or_none(matches[0])
    return None


def _structured_target_price_from_value(value: Any) -> float | None:
    if isinstance(value, Mapping):
        for key in STOCK_TARGET_PRICE_NUMERIC_KEYS:
            parsed = _structured_float_or_none(value.get(key))
            if parsed is not None:
                return parsed
        return None
    return _structured_float_or_none(value)


def _mapping_target_price(mapping: Mapping[str, Any]) -> float | None:
    for key in STOCK_TARGET_PRICE_VALUE_KEYS:
        parsed = _structured_target_price_from_value(mapping.get(key))
        if parsed is not None:
            return parsed
    return None


def _target_price_provenance_from_mapping(mapping: Mapping[str, Any]) -> str:
    for key in ("target_price_source_grounded", "price_target_source_grounded"):
        if mapping.get(key) is True:
            return "source_grounded"
        if mapping.get(key) is False:
            return "not_source_grounded"
    for key in STOCK_TARGET_PRICE_VALUE_KEYS:
        nested = _ensure_mapping(mapping.get(key))
        for provenance_key in STOCK_TARGET_PRICE_PROVENANCE_KEYS:
            provenance = str(nested.get(provenance_key) or "").strip().lower()
            if provenance:
                return provenance
    for key in STOCK_TARGET_PRICE_PROVENANCE_KEYS:
        provenance = str(mapping.get(key) or "").strip().lower()
        if provenance:
            return provenance
    return ""


def _stock_target_price_info(claim: Mapping[str, Any]) -> dict[str, Any]:
    target = _ensure_mapping(claim.get("target"))
    target_price = _mapping_target_price(target)
    if target_price is None:
        target_price = _mapping_target_price(claim)
    if target_price is None or target_price <= 0:
        return {}

    provenance = (
        _target_price_provenance_from_mapping(target)
        or _target_price_provenance_from_mapping(claim)
    )
    claim_provenance = str(claim.get("claim_provenance") or "").strip().lower()
    if provenance == "not_source_grounded":
        return {}
    if provenance != "source_grounded" and claim_provenance != "source_grounded":
        return {}
    if not provenance:
        provenance = "claim_source_grounded"
    return {
        "target_price": round(target_price, 8),
        "target_price_provenance": provenance,
        "target_price_source_grounded": True,
    }


def _stock_target_price_hit_fields(
    *,
    target_price_info: Mapping[str, Any],
    direction: str,
    entry_price: float,
    exit_price: float,
) -> dict[str, Any]:
    target_price = _float_or_none(target_price_info.get("target_price"))
    if target_price is None:
        return {}
    target_price_hit = (
        exit_price >= target_price if direction == "positive" else exit_price <= target_price
    )
    return {
        **target_price_info,
        "target_price_hit": bool(target_price_hit),
        "target_price_entry_price": round(entry_price, 8),
        "target_price_eval_price": round(exit_price, 8),
        "target_price_hit_policy": STOCK_TARGET_PRICE_HIT_POLICY,
    }


def build_forecast_ledger_records(
    forecast_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for claim in forecast_rows:
        target = _ensure_mapping(claim.get("target"))
        benchmark = _ensure_mapping(claim.get("benchmark"))
        horizon = _ensure_mapping(claim.get("horizon"))
        required_ready = (
            str(claim.get("forecast_testability") or "") == "testable"
            and _target_id(target) != "unknown"
            and bool(benchmark)
            and str(claim.get("direction") or "unknown") not in {"", "unknown"}
            and _horizon_bucket(horizon) != "unknown"
        )
        family_payload = {
            "forecast_type": claim.get("forecast_type") or "unknown",
            "target": _target_id(target),
            "benchmark": benchmark.get("benchmark_id") or benchmark.get("benchmark_type") or "unknown",
            "horizon_bucket": _horizon_bucket(horizon),
        }
        family_id = _stable_id("FF", family_payload)
        cluster_id = _stable_id(
            "CONSENSUS",
            {
                "forecast_family_id": family_id,
                "direction": claim.get("direction"),
                "claim_text": claim.get("claim_text"),
            },
        )
        records.append(
            {
                "ledger_id": _stable_id(
                    "RFL",
                    {
                        "forecast_claim_id": claim.get("forecast_claim_id"),
                        "version": 1,
                    },
                ),
                "forecast_claim_id": str(claim.get("forecast_claim_id") or ""),
                "report_id": str(claim.get("report_id") or ""),
                "as_of_datetime": str(claim.get("signal_datetime") or ""),
                "forecast_family_id": family_id,
                "dedup_cluster_id": cluster_id,
                "consensus_cluster_id": cluster_id,
                "copying_risk_bucket": "unknown",
                "source_dependency_score": None,
                "independent_viewpoint_count": None,
                "test_status": "ready_for_outcome_labeling"
                if required_ready
                else "not_ready_insufficient_mapping",
                "version": 1,
                "immutable": True,
            }
        )
    return records


def build_outcome_labeling_readiness_report(
    *,
    forecast_rows: Sequence[Mapping[str, Any]],
    forecast_ledger_rows: Sequence[Mapping[str, Any]],
    industry_etf_proxy_readiness: Mapping[str, Any] | None = None,
    stock_price_proxy_readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    gap_counts: dict[str, int] = {}
    unlabelable_gap_counts: dict[str, int] = {}
    test_status_counts: dict[str, int] = {}
    ready_ids: list[str] = []
    standard_blocked_ids: list[str] = []
    blocked_ids: list[str] = []
    industry_proxy = dict(industry_etf_proxy_readiness or {})
    stock_proxy = dict(stock_price_proxy_readiness or {})
    industry_proxy_label_ready_ids = [
        str(claim_id)
        for claim_id in _ensure_list(
            industry_proxy.get("labelable_forecast_claim_ids")
        )
        if str(claim_id).strip()
    ]
    stock_proxy_label_ready_ids = [
        str(claim_id)
        for claim_id in _ensure_list(stock_proxy.get("labelable_forecast_claim_ids"))
        if str(claim_id).strip()
    ]
    proxy_label_ready_ids = sorted(
        set(industry_proxy_label_ready_ids) | set(stock_proxy_label_ready_ids)
    )
    proxy_label_ready_id_set = set(proxy_label_ready_ids)
    proxy_label_only_ids: list[str] = []
    forecast_by_id = {
        str(row.get("forecast_claim_id") or ""): row for row in forecast_rows
    }
    for ledger in forecast_ledger_rows:
        forecast_claim_id = str(ledger.get("forecast_claim_id") or "")
        status = str(ledger.get("test_status") or "unknown")
        test_status_counts[status] = test_status_counts.get(status, 0) + 1
        if status == "ready_for_outcome_labeling":
            ready_ids.append(forecast_claim_id)
            continue
        standard_blocked_ids.append(forecast_claim_id)
        has_proxy_label_path = forecast_claim_id in proxy_label_ready_id_set
        if has_proxy_label_path:
            proxy_label_only_ids.append(forecast_claim_id)
        else:
            blocked_ids.append(forecast_claim_id)
        forecast = forecast_by_id.get(forecast_claim_id) or {}
        extraction_quality = _ensure_mapping(forecast.get("extraction_quality"))
        mapping_gaps = [
            str(gap)
            for gap in _ensure_list(extraction_quality.get("mapping_gaps"))
            if str(gap).strip()
        ] or ["unknown_mapping_gap"]
        for gap in mapping_gaps:
            gap_counts[gap] = gap_counts.get(gap, 0) + 1
            if not has_proxy_label_path:
                unlabelable_gap_counts[gap] = unlabelable_gap_counts.get(gap, 0) + 1
    if blocked_ids:
        blocked_reason = (
            "forecast_mapping_insufficient_for_unlabelable_claims"
            if ready_ids or proxy_label_only_ids
            else "forecast_mapping_insufficient_for_all_claims"
        )
    else:
        blocked_reason = ""
    return {
        "readiness_id": "RKE-REPORT-OUTCOME-LABELING-READINESS",
        "forecast_claim_count": len(forecast_rows),
        "forecast_ledger_count": len(forecast_ledger_rows),
        "ready_for_outcome_labeling_count": len(ready_ids),
        "blocked_count": len(blocked_ids),
        "standard_blocked_count": len(standard_blocked_ids),
        "proxy_label_ready_count": len(proxy_label_ready_ids),
        "industry_proxy_label_ready_count": len(industry_proxy_label_ready_ids),
        "stock_proxy_label_ready_count": len(stock_proxy_label_ready_ids),
        "proxy_label_only_ready_count": len(proxy_label_only_ids),
        "test_status_counts": dict(sorted(test_status_counts.items())),
        "mapping_gap_counts": dict(sorted(gap_counts.items())),
        "unlabelable_mapping_gap_counts": dict(sorted(unlabelable_gap_counts.items())),
        "ready_forecast_claim_ids": ready_ids,
        "standard_blocked_forecast_claim_ids": standard_blocked_ids,
        "proxy_label_ready_forecast_claim_ids": proxy_label_ready_ids,
        "industry_proxy_label_ready_forecast_claim_ids": industry_proxy_label_ready_ids,
        "stock_proxy_label_ready_forecast_claim_ids": stock_proxy_label_ready_ids,
        "proxy_label_only_ready_forecast_claim_ids": proxy_label_only_ids,
        "blocked_forecast_claim_ids": blocked_ids,
        "blocked_reason": blocked_reason,
        "minimum_required_mapping": [
            "target",
            "benchmark",
            "direction",
            "horizon",
        ],
        "policy": (
            "outcome labels are generated only for source-grounded testable "
            "forecasts with target, benchmark, direction, horizon, and PIT data; "
            "industry ETF and stock price proxy labels may additionally evaluate "
            "governed target-direction claims on fixed PIT windows without "
            "promoting them to production use"
        ),
        "industry_etf_proxy_readiness": industry_proxy,
        "stock_price_proxy_readiness": stock_proxy,
        "next_actions": [
            "improve extractor prompt to bind ts_code/title entities into target when source text supports it",
            "route unmapped claims through manual gold-set review instead of fabricating labels",
            "evaluate industry research with ETF proxy windows when sector mapping and PIT data are available",
            "evaluate stock research with qlib cn_data windows when ts_code mapping and PIT data are available",
            "run PIT outcome labeler only after ready_for_outcome_labeling_count is positive",
        ],
    }


def _resolve_qlib_data_dir(root_path: Path, qlib_dir: str | Path) -> Path:
    raw = Path(os.path.expanduser(str(qlib_dir)))
    return raw if raw.is_absolute() else root_path / raw


def _resolve_qlib_etf_dir(root_path: Path, qlib_etf_dir: str | Path) -> Path:
    return _resolve_qlib_data_dir(root_path, qlib_etf_dir)


def _resolve_qlib_stock_dir(root_path: Path, qlib_stock_dir: str | Path) -> Path:
    return _resolve_qlib_data_dir(root_path, qlib_stock_dir)


def _qlib_symbol(symbol: str) -> str:
    cleaned = str(symbol or "").strip()
    if "." in cleaned:
        code, market = cleaned.split(".", 1)
        return f"{market.lower()}{code}"
    return cleaned.lower()


def _read_trading_calendar(qlib_dir: Path) -> list[str]:
    calendar_path = qlib_dir / "calendars/day.txt"
    if not calendar_path.exists():
        return []
    return [
        line.strip()
        for line in calendar_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _read_qlib_series(
    qlib_dir: Path,
    symbol: str,
    field: str = "adjclose",
) -> tuple[int, list[float]]:
    path = qlib_dir / "features" / _qlib_symbol(symbol) / f"{field}.day.bin"
    if not path.exists():
        return 0, []
    data = path.read_bytes()
    if len(data) < 8 or len(data) % 4 != 0:
        return 0, []
    values = struct.unpack(f"<{len(data) // 4}f", data)
    return int(values[0]), [float(value) for value in values[1:]]


def _series_value_at_calendar_index(
    *,
    start_index: int,
    values: Sequence[float],
    calendar_index: int,
) -> float | None:
    offset = calendar_index - start_index
    if offset < 0 or offset >= len(values):
        return None
    value = values[offset]
    if value != value or value <= 0:
        return None
    return value


def _series_raw_value_at_calendar_index(
    *,
    start_index: int,
    values: Sequence[float],
    calendar_index: int,
) -> float | None:
    offset = calendar_index - start_index
    if offset < 0 or offset >= len(values):
        return None
    value = values[offset]
    if value != value:
        return None
    return value


def _calendar_index_for_date(calendar: Sequence[str], date_value: str) -> int | None:
    date_key = _date_key(date_value)
    if not date_key:
        return None
    for index, item in enumerate(calendar):
        if item == date_key:
            return index
    return None


def _series_value_at_date(
    *,
    calendar: Sequence[str],
    start_index: int,
    values: Sequence[float],
    date_value: str,
) -> float | None:
    calendar_index = _calendar_index_for_date(calendar, date_value)
    if calendar_index is None:
        return None
    return _series_value_at_calendar_index(
        start_index=start_index,
        values=values,
        calendar_index=calendar_index,
    )


def _next_calendar_index(calendar: Sequence[str], date_value: str) -> int | None:
    date_key = _date_key(date_value)
    if not date_key:
        return None
    for index, item in enumerate(calendar):
        if item >= date_key:
            return index
    return None


def _entry_calendar_index(calendar: Sequence[str], signal_datetime: str) -> int | None:
    date_key = _date_key(signal_datetime)
    if not date_key:
        return None
    first_strictly_after_signal = None
    for index, item in enumerate(calendar):
        if item > date_key:
            first_strictly_after_signal = index
            break
    if first_strictly_after_signal is None:
        return None
    entry_index = first_strictly_after_signal + max(
        0,
        INDUSTRY_ETF_ENTRY_LAG_TRADING_DAYS - 1,
    )
    if entry_index >= len(calendar):
        return None
    return entry_index


def _entry_calendar_date(calendar: Sequence[str], signal_datetime: str) -> str:
    entry_index = _entry_calendar_index(calendar, signal_datetime)
    return calendar[entry_index] if entry_index is not None else ""


def _exit_calendar_date(
    calendar: Sequence[str],
    entry_index: int,
    horizon_days: int,
) -> str:
    exit_index = entry_index + int(horizon_days)
    if exit_index < 0 or exit_index >= len(calendar):
        return ""
    return calendar[exit_index]


def _date_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if match:
        return match.group(0)
    return text[:10]


def _is_industry_research_report(report_type: Any) -> bool:
    return "行业" in str(report_type or "")


def _is_potential_stock_report(metadata: Mapping[str, Any]) -> bool:
    report_type = str(metadata.get("report_type") or "")
    return bool(str(metadata.get("ts_code") or "").strip()) or any(
        marker in report_type for marker in ("公司", "个股")
    )


def _normalize_ts_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    match = re.fullmatch(r"(\d{6})\.(SH|SZ|BJ)", text)
    if not match:
        return ""
    code, market = match.groups()
    if market == "BJ" and not code.startswith("920"):
        return ""
    return f"{code}.{market}"


def _is_stock_forecast_claim(
    claim: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> bool:
    target = _ensure_mapping(claim.get("target"))
    target_type = str(target.get("target_type") or "").strip().lower()
    if target_type == "stock":
        return True
    return _is_potential_stock_report(metadata)


def _stock_target_resolution(
    claim: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> dict[str, str]:
    target = _ensure_mapping(claim.get("target"))
    target_type = str(target.get("target_type") or "").strip().lower()
    metadata_ts_code = _normalize_ts_code(metadata.get("ts_code"))
    llm_ts_code = _normalize_ts_code(target.get("target_id"))
    raw_target = str(target.get("target_id") or target.get("target_name") or "").strip()
    if target_type != "stock":
        return {
            "ts_code": "",
            "target_resolution_source": "",
            "gap": "stock_target_mapping_missing",
            "metadata_ts_code": metadata_ts_code,
            "llm_target_id": raw_target,
        }
    if metadata_ts_code and llm_ts_code and metadata_ts_code != llm_ts_code:
        return {
            "ts_code": "",
            "target_resolution_source": "",
            "gap": "stock_target_conflict",
            "metadata_ts_code": metadata_ts_code,
            "llm_target_id": llm_ts_code,
        }
    if metadata_ts_code and llm_ts_code:
        return {
            "ts_code": metadata_ts_code,
            "target_resolution_source": "metadata_and_llm_target_id",
            "gap": "",
            "metadata_ts_code": metadata_ts_code,
            "llm_target_id": llm_ts_code,
        }
    if metadata_ts_code:
        return {
            "ts_code": metadata_ts_code,
            "target_resolution_source": "metadata_ts_code",
            "gap": "",
            "metadata_ts_code": metadata_ts_code,
            "llm_target_id": raw_target,
        }
    if llm_ts_code:
        return {
            "ts_code": llm_ts_code,
            "target_resolution_source": "llm_target_id",
            "gap": "",
            "metadata_ts_code": "",
            "llm_target_id": llm_ts_code,
        }
    return {
        "ts_code": "",
        "target_resolution_source": "",
        "gap": "stock_target_missing" if not raw_target else "stock_target_mapping_missing",
        "metadata_ts_code": metadata_ts_code,
        "llm_target_id": raw_target,
    }


def _industry_etf_window_role(horizon_days: int) -> str:
    if horizon_days <= 20:
        return "short"
    if horizon_days <= 60:
        return "medium"
    return "long"


def _industry_etf_window_effective_weight(horizon_days: int) -> float:
    role = _industry_etf_window_role(horizon_days)
    return INDUSTRY_ETF_PROXY_WINDOW_EFFECTIVE_WEIGHTS[role]


def _stock_price_proxy_window_role(horizon_days: int) -> str:
    if horizon_days <= 20:
        return "short"
    if horizon_days <= 60:
        return "medium"
    return "long"


def _stock_price_proxy_window_effective_weight(horizon_days: int) -> float:
    return STOCK_PRICE_PROXY_WINDOW_EFFECTIVE_WEIGHTS.get(int(horizon_days), 0.0)


def _industry_etf_claim_window_alignment(
    *,
    claim_horizon: Mapping[str, Any],
    horizon_days: int,
) -> str:
    if not claim_horizon:
        return "fixed_window_no_source_horizon"
    min_days = _int_or_none(claim_horizon.get("min_days"))
    max_days = _int_or_none(
        claim_horizon.get("preferred_days") or claim_horizon.get("max_days")
    )
    if min_days is not None and horizon_days < min_days:
        return "shorter_than_source_horizon"
    if max_days is not None and horizon_days > max_days:
        return "beyond_source_horizon"
    return "within_source_horizon"


def _stock_price_claim_window_alignment(
    *,
    claim_horizon: Mapping[str, Any],
    horizon_days: int,
) -> str:
    return _industry_etf_claim_window_alignment(
        claim_horizon=claim_horizon,
        horizon_days=horizon_days,
    )


def _industry_etf_temporal_validation_summary(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    ordered = sorted(records, key=lambda row: int(row.get("horizon_days") or 0))
    hit_days = [
        int(row.get("horizon_days") or 0)
        for row in ordered
        if row.get("directional_hit") is True
    ]
    miss_days = [
        int(row.get("horizon_days") or 0)
        for row in ordered
        if row.get("directional_hit") is not True
    ]
    available_days = [int(row.get("horizon_days") or 0) for row in ordered]
    short_record = next(
        (row for row in ordered if str(row.get("window_role") or "") == "short"),
        None,
    )
    long_record = next(
        (row for row in reversed(ordered) if str(row.get("window_role") or "") == "long"),
        ordered[-1] if ordered else None,
    )
    short_hit = (
        bool(short_record.get("directional_hit"))
        if short_record is not None
        else None
    )
    long_hit = (
        bool(long_record.get("directional_hit"))
        if long_record is not None
        else None
    )
    if ordered and len(hit_days) == len(ordered):
        bucket = "consistent_hit"
    elif ordered and not hit_days:
        bucket = "consistent_miss"
    elif short_hit is False and long_hit is True:
        bucket = "short_miss_long_hit"
    elif short_hit is True and long_hit is False:
        bucket = "short_hit_long_miss"
    else:
        bucket = "mixed_windows"
    return {
        "policy": (
            "industry research is validated on fixed ETF proxy windows; short, "
            "medium, and long windows are retained as separate evidence"
        ),
        "available_window_days": available_days,
        "hit_window_days": hit_days,
        "miss_window_days": miss_days,
        "short_window_directional_hit": short_hit,
        "long_window_directional_hit": long_hit,
        "long_window_hit_retained": long_hit is True,
        "temporal_validation_bucket": bucket,
        "window_evidence_policy": (
            "do_not_collapse_multi_window_outcome_to_single_label"
        ),
    }


def _stock_price_temporal_validation_summary(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    ordered = sorted(records, key=lambda row: int(row.get("horizon_days") or 0))
    hit_days = [
        int(row.get("horizon_days") or 0)
        for row in ordered
        if row.get("directional_hit") is True
    ]
    miss_days = [
        int(row.get("horizon_days") or 0)
        for row in ordered
        if row.get("directional_hit") is not True
    ]
    short_record = next(
        (row for row in ordered if str(row.get("window_role") or "") == "short"),
        None,
    )
    long_record = next(
        (row for row in reversed(ordered) if str(row.get("window_role") or "") == "long"),
        ordered[-1] if ordered else None,
    )
    short_hit = (
        bool(short_record.get("directional_hit"))
        if short_record is not None
        else None
    )
    long_hit = (
        bool(long_record.get("directional_hit"))
        if long_record is not None
        else None
    )
    if ordered and len(hit_days) == len(ordered):
        bucket = "consistent_hit"
    elif ordered and not hit_days:
        bucket = "consistent_miss"
    elif short_hit is False and long_hit is True:
        bucket = "short_miss_long_hit"
    elif short_hit is True and long_hit is False:
        bucket = "short_hit_long_miss"
    else:
        bucket = "mixed_windows"
    return {
        "policy": (
            "stock research is validated on fixed PIT stock price windows; "
            "short, medium, and long windows are retained as separate evidence"
        ),
        "available_window_days": [
            int(row.get("horizon_days") or 0) for row in ordered
        ],
        "hit_window_days": hit_days,
        "miss_window_days": miss_days,
        "short_window_directional_hit": short_hit,
        "long_window_directional_hit": long_hit,
        "long_window_hit_retained": long_hit is True,
        "temporal_validation_bucket": bucket,
        "window_evidence_policy": (
            "do_not_collapse_multi_window_outcome_to_single_label"
        ),
    }


def _has_positive_volume_at(
    *,
    start_index: int,
    values: Sequence[float],
    calendar_index: int,
) -> bool | None:
    if not values:
        return None
    volume = _series_raw_value_at_calendar_index(
        start_index=start_index,
        values=values,
        calendar_index=calendar_index,
    )
    if volume is None:
        return None
    return volume > 0


def _entry_limit_locked(
    *,
    direction: str,
    previous_close: float | None,
    open_price: float | None,
    high_price: float | None,
    low_price: float | None,
    close_price: float | None,
) -> bool | None:
    if None in {previous_close, open_price, high_price, low_price, close_price}:
        return None
    if previous_close is None or previous_close <= 0:
        return None
    assert open_price is not None
    assert high_price is not None
    assert low_price is not None
    assert close_price is not None
    one_price_locked = (
        abs(open_price - high_price) < 1e-9
        and abs(open_price - low_price) < 1e-9
        and abs(open_price - close_price) < 1e-9
    )
    pct = close_price / previous_close - 1.0
    if direction == "positive":
        return one_price_locked and pct >= 0.095
    if direction == "negative":
        return one_price_locked and pct <= -0.095
    return None


def _exit_limit_locked(
    *,
    direction: str,
    previous_close: float | None,
    open_price: float | None,
    high_price: float | None,
    low_price: float | None,
    close_price: float | None,
) -> bool | None:
    if direction == "positive":
        exit_direction = "negative"
    elif direction == "negative":
        exit_direction = "positive"
    else:
        return None
    return _entry_limit_locked(
        direction=exit_direction,
        previous_close=previous_close,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
    )


def _source_report_metadata(
    metadata_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    return {str(row.get("source_id") or ""): row for row in metadata_rows}


def _increment_count(counts: dict[str, int], key: Any, *, default: str = "unknown") -> None:
    normalized = str(key or "").strip() or default
    counts[normalized] = counts.get(normalized, 0) + 1


def _is_pdf_ready(pdf: Mapping[str, Any]) -> bool:
    return str(pdf.get("status") or "") in {"cached", "downloaded"}


def _is_markdown_ready(markdown: Mapping[str, Any]) -> bool:
    return str(markdown.get("status") or "") in {
        "cached",
        "converted",
        "converted_text_source",
    }


def _markdown_non_empty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _markdown_line_key(line: str) -> str:
    return re.sub(r"\s+", "", line).strip()


def _markdown_has_conversion_instability(markdown: Mapping[str, Any]) -> bool:
    if bool(markdown.get("conversion_instability")):
        return True
    stability_status = str(markdown.get("conversion_stability_status") or "").strip()
    return stability_status in {"unstable", "inconsistent", "failed"}


def _markdown_is_toc_line(line: str) -> bool:
    stripped = line.strip().strip("#").strip()
    lowered = stripped.lower()
    if lowered in {"目录", "目 录", "contents", "table of contents"}:
        return True
    if re.search(r"(\.{2,}|…{1,}|-{2,})\s*\d+\s*$", stripped):
        return True
    if re.match(
        r"^(第?[一二三四五六七八九十\d]+[章节\.、\s]).{1,40}\s+\d+\s*$",
        stripped,
    ):
        return True
    return False


def _markdown_is_toc_only(text: str) -> bool:
    lines = _markdown_non_empty_lines(text)
    if len(lines) < 3:
        return False
    has_toc_heading = any(
        _markdown_line_key(line).lower()
        in {"#目录", "##目录", "目录", "目錄", "contents", "tableofcontents"}
        for line in lines[:5]
    )
    if not has_toc_heading:
        return False
    toc_line_count = sum(1 for line in lines if _markdown_is_toc_line(line))
    return toc_line_count / max(len(lines), 1) >= 0.70


def _markdown_empty_table_dominant(text: str) -> bool:
    table_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("|") and line.strip().endswith("|")
    ]
    if len(table_lines) < 3:
        return False
    empty_or_separator_count = 0
    for line in table_lines:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells:
            continue
        if all(not cell or re.fullmatch(r"[:\-\s]+", cell) for cell in cells):
            empty_or_separator_count += 1
    return (
        empty_or_separator_count / max(len(table_lines), 1)
        > MARKDOWN_QUALITY_EMPTY_TABLE_RATIO_MAX
    )


def _markdown_image_only(text: str) -> bool:
    lines = _markdown_non_empty_lines(text)
    if not lines:
        return False
    image_line_count = sum(
        1
        for line in lines
        if re.search(
            (
                r"!\[[^\]]*\]\([^)]+\)|<img\b|\[图片\]|图片未识别|"
                r"image\s+not\s+recognized"
            ),
            line,
            re.I,
        )
    )
    if image_line_count == 0:
        return False
    without_images = re.sub(
        r"!\[[^\]]*\]\([^)]+\)|<img[^>]*>|\[图片\]|图片未识别",
        "",
        text,
        flags=re.I,
    )
    prose = re.sub(r"[\W_]+", "", without_images, flags=re.UNICODE)
    return (
        image_line_count / max(len(lines), 1) >= 0.50
        and len(prose) < MARKDOWN_QUALITY_MIN_BYTES
    )


def _markdown_repeated_line_noise(text: str) -> bool:
    keys: list[str] = []
    for line in _markdown_non_empty_lines(text):
        key = _markdown_line_key(line)
        if len(key) >= 4:
            keys.append(key)
    if len(keys) < 8:
        return False
    counts: dict[str, int] = {}
    for key in keys:
        counts[key] = counts.get(key, 0) + 1
    max_count = max(counts.values(), default=0)
    repeated_count = sum(count for count in counts.values() if count > 1)
    return (
        max_count >= MARKDOWN_QUALITY_REPEATED_LINE_MIN_COUNT
        and repeated_count / max(len(keys), 1) > MARKDOWN_QUALITY_REPEATED_LINE_RATIO_MAX
    )


def _markdown_quality_gap(markdown: Mapping[str, Any], text: str | None = None) -> str:
    stored_gap = str(markdown.get("quality_gap") or "").strip()
    if stored_gap:
        return stored_gap
    status = str(markdown.get("status") or "not_attempted")
    if not _is_markdown_ready(markdown):
        blocker = str(markdown.get("blocker") or "").strip()
        return blocker or f"markdown_status_{status}"
    byte_count = int(markdown.get("bytes") or 0)
    if byte_count <= 0:
        return "markdown_empty"
    if bool(markdown.get("timed_out")):
        return "markdown_timed_out"
    if _markdown_has_conversion_instability(markdown):
        return "markdown_conversion_instability"
    if text is not None:
        normalized = re.sub(r"\s+", "", text)
        if not normalized:
            return "markdown_empty"
        replacement_ratio = normalized.count("\ufffd") / max(len(normalized), 1)
        if replacement_ratio > 0.05:
            return "markdown_garbled_text"
        disclaimer_stripped = re.sub(
            r"(免责声明|风险提示|重要声明|法律声明|投资有风险)",
            "",
            normalized,
        )
        if "免责声明" in normalized and len(disclaimer_stripped) < MARKDOWN_QUALITY_MIN_BYTES:
            return "markdown_disclaimer_only"
        if _markdown_is_toc_only(text):
            return "markdown_toc_only"
        if _markdown_empty_table_dominant(text):
            return "markdown_empty_table_dominant"
        if _markdown_image_only(text):
            return "markdown_image_only"
        if _markdown_repeated_line_noise(text):
            return "markdown_repeated_line_noise"
        if not any(marker in text for marker in MARKDOWN_STRUCTURE_MARKERS):
            return "markdown_structure_signal_missing"
    if byte_count < MARKDOWN_QUALITY_MIN_BYTES:
        return "markdown_too_short"
    return ""


def _annotate_markdown_quality(
    markdown: Mapping[str, Any],
    markdown_path: Path,
) -> dict[str, Any]:
    annotated = dict(markdown)
    text: str | None = None
    if markdown_path.exists() and markdown_path.stat().st_size > 0:
        text = markdown_path.read_text(encoding="utf-8", errors="replace")
    gap = _markdown_quality_gap(annotated, text)
    annotated["quality_gate_status"] = "blocked" if gap else "passed"
    annotated["quality_gap"] = gap
    return annotated


def build_markdown_coverage_summary(
    *,
    run_id: str,
    metadata_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    report_type_counts: dict[str, int] = {}
    sector_bucket_counts: dict[str, int] = {}
    conversion_backend_counts: dict[str, int] = {}
    quality_gap_counts: dict[str, int] = {}
    pdf_ready_count = 0
    markdown_ready_count = 0
    markdown_quality_pass_count = 0
    llm_extraction_processed_count = 0
    llm_extraction_without_quality_pass_count = 0
    retry_queue_count = 0
    for row in metadata_rows:
        _increment_count(report_type_counts, row.get("report_type"))
        _increment_count(sector_bucket_counts, row.get("sector"))
        pdf = _ensure_mapping(row.get("pdf"))
        markdown = _ensure_mapping(row.get("markdown"))
        if _is_pdf_ready(pdf):
            pdf_ready_count += 1
        backend = str(markdown.get("backend") or "").strip()
        if backend:
            _increment_count(conversion_backend_counts, backend)
        if _is_markdown_ready(markdown):
            markdown_ready_count += 1
        gap = _markdown_quality_gap(markdown)
        if gap:
            _increment_count(quality_gap_counts, gap)
            if any(marker in gap for marker in ("mineru", "timeout", "failed", "not_found")):
                retry_queue_count += 1
        else:
            markdown_quality_pass_count += 1
        extraction = _ensure_mapping(row.get("extraction"))
        if str(extraction.get("llm_status") or "") == "processed":
            llm_extraction_processed_count += 1
            if gap:
                llm_extraction_without_quality_pass_count += 1
    coverage_targets = {
        "selected_report_count_min": MARKDOWN_COVERAGE_MIN_SELECTED_REPORTS,
        "markdown_ready_count_min": MARKDOWN_COVERAGE_MIN_MARKDOWN_READY,
        "markdown_quality_pass_count_min": MARKDOWN_COVERAGE_MIN_QUALITY_PASS,
        "llm_extraction_processed_count_min": (
            MARKDOWN_COVERAGE_MIN_LLM_EXTRACTION_PROCESSED
        ),
    }
    coverage_gate_blockers: list[str] = []
    if len(metadata_rows) < MARKDOWN_COVERAGE_MIN_SELECTED_REPORTS:
        coverage_gate_blockers.append("selected_report_count_below_p9_target")
    if markdown_ready_count < MARKDOWN_COVERAGE_MIN_MARKDOWN_READY:
        coverage_gate_blockers.append("markdown_ready_count_below_p9_target")
    if markdown_quality_pass_count < MARKDOWN_COVERAGE_MIN_QUALITY_PASS:
        coverage_gate_blockers.append("markdown_quality_pass_count_below_p9_target")
    if (
        llm_extraction_processed_count
        < MARKDOWN_COVERAGE_MIN_LLM_EXTRACTION_PROCESSED
    ):
        coverage_gate_blockers.append(
            "llm_extraction_processed_count_below_p9_target"
        )
    if llm_extraction_without_quality_pass_count:
        coverage_gate_blockers.append("llm_extraction_without_quality_pass")
    return {
        "coverage_id": "RKE-REPORT-MARKDOWN-COVERAGE-SUMMARY",
        "run_id": run_id,
        "selected_report_count": len(metadata_rows),
        "pdf_download_ready_count": pdf_ready_count,
        "markdown_ready_count": markdown_ready_count,
        "markdown_quality_pass_count": markdown_quality_pass_count,
        "llm_extraction_processed_count": llm_extraction_processed_count,
        "llm_extraction_without_quality_pass_count": (
            llm_extraction_without_quality_pass_count
        ),
        "coverage_targets": coverage_targets,
        "coverage_gate_status": (
            "passed" if not coverage_gate_blockers else "blocked"
        ),
        "coverage_gate_blockers": coverage_gate_blockers,
        "markdown_quality_gap_counts": dict(sorted(quality_gap_counts.items())),
        "report_type_counts": dict(sorted(report_type_counts.items())),
        "sector_bucket_counts": dict(sorted(sector_bucket_counts.items())),
        "conversion_backend_counts": dict(sorted(conversion_backend_counts.items())),
        "retry_queue_count": retry_queue_count,
        "private_artifact_redaction_policy": (
            "public coverage summary stores aggregate counts only; no "
            "source-specific content, retrieval locator, local file reference, "
            "or report prose is allowed"
        ),
    }


def build_default_industry_etf_proxy_map_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sector_name, mapping in sorted(INDUSTRY_ETF_PROXY_MAPPING.items()):
        etf_symbol = str(mapping.get("etf_symbol") or "")
        etf_name = str(mapping.get("mapping_label") or "")
        rows.append(
            {
                "mapping_id": _stable_id(
                    "IETF-MAP",
                    {
                        "sector_name": sector_name,
                        "etf_symbol": etf_symbol,
                        "version": INDUSTRY_ETF_MAPPING_VERSION,
                    },
                ),
                "mapping_version": INDUSTRY_ETF_MAPPING_VERSION,
                "sector_name": sector_name,
                "sector_aliases": [sector_name],
                "taxonomy": "operator_seeded_tushare_industry",
                "etf_symbol": etf_symbol,
                "etf_name": etf_name,
                "mapping_label": etf_name,
                "benchmark_symbol": INDUSTRY_ETF_BENCHMARK_SYMBOL,
                "benchmark_source": INDUSTRY_ETF_BENCHMARK_SOURCE,
                "benchmark_family": INDUSTRY_ETF_BENCHMARK_FAMILY,
                "cost_model_id": INDUSTRY_ETF_COST_MODEL_ID,
                "mapping_confidence": "operator_seeded_exact_sector",
                "mapping_rationale": (
                    "Operator-seeded sector-to-ETF proxy used for governed "
                    "industry research outcome labels."
                ),
                "effective_from": "",
                "effective_to": "",
                "status": "primary",
                "review_required": False,
            }
        )
    return rows


def _read_industry_etf_proxy_map_rows(registry_dir: Path) -> list[Mapping[str, Any]]:
    map_path = registry_dir / "industry_etf_proxy_map.jsonl"
    if not map_path.exists():
        return build_default_industry_etf_proxy_map_rows()
    rows, _errors = load_jsonl_with_errors(map_path, label="industry_etf_proxy_map")
    mapping_rows = [row for row in rows if isinstance(row, Mapping)]
    return mapping_rows or build_default_industry_etf_proxy_map_rows()


def _industry_etf_proxy_for_sector(
    sector: str,
    mapping_rows: Sequence[Mapping[str, Any]] | None = None,
    *,
    as_of_datetime: str = "",
) -> Mapping[str, Any] | None:
    rows = list(mapping_rows or build_default_industry_etf_proxy_map_rows())
    normalized = str(sector or "").strip()
    primary_rows = [
        row
        for row in rows
        if str(row.get("status") or "primary") == "primary"
        and _mapping_effective_for_datetime(row, as_of_datetime)
    ]
    for row in primary_rows:
        names = [
            str(row.get("sector_name") or ""),
            *[str(item) for item in _ensure_list(row.get("sector_aliases"))],
        ]
        for name in names:
            if not name:
                continue
            if normalized == name or name in normalized:
                return row
    return None


def _mapping_effective_for_datetime(
    row: Mapping[str, Any],
    as_of_datetime: str,
) -> bool:
    as_of_date = _date_key(as_of_datetime)
    if not as_of_date:
        return True
    effective_from = _date_key(str(row.get("effective_from") or ""))
    effective_to = _date_key(str(row.get("effective_to") or ""))
    if effective_from and as_of_date < effective_from:
        return False
    if effective_to and as_of_date > effective_to:
        return False
    return True


def _industry_mapping_benchmark_symbol(row: Mapping[str, Any]) -> str:
    return str(row.get("benchmark_symbol") or INDUSTRY_ETF_BENCHMARK_SYMBOL)


def _series_available_dates(
    *,
    calendar: Sequence[str],
    start_index: int,
    values: Sequence[float],
) -> list[str]:
    dates: list[str] = []
    for offset, value in enumerate(values):
        calendar_index = start_index + offset
        if calendar_index >= len(calendar):
            break
        if value == value and value > 0:
            dates.append(calendar[calendar_index])
    return dates


def build_industry_etf_proxy_pit_availability(
    *,
    root_path: Path,
    qlib_etf_dir: str | Path,
    mapping_rows: Sequence[Mapping[str, Any]],
    forecast_rows: Sequence[Mapping[str, Any]] = (),
    metadata_rows: Sequence[Mapping[str, Any]] = (),
    windows_days: Sequence[int] = INDUSTRY_ETF_PROXY_WINDOWS_DAYS,
) -> dict[str, Any]:
    qlib_dir = _resolve_qlib_etf_dir(root_path, qlib_etf_dir)
    calendar = _read_trading_calendar(qlib_dir)
    benchmark_cache: dict[str, tuple[int, list[float]]] = {}

    def benchmark_series(symbol: str) -> tuple[int, list[float]]:
        benchmark_symbol = symbol or INDUSTRY_ETF_BENCHMARK_SYMBOL
        if benchmark_symbol not in benchmark_cache:
            benchmark_cache[benchmark_symbol] = _read_qlib_series(
                qlib_dir,
                benchmark_symbol,
            )
        return benchmark_cache[benchmark_symbol]

    metadata_by_source = _source_report_metadata(metadata_rows)
    mapping_records: list[dict[str, Any]] = []
    aggregate_gap_counts: dict[str, int] = {}
    for row in mapping_rows:
        etf_symbol = str(row.get("etf_symbol") or "")
        benchmark_symbol = _industry_mapping_benchmark_symbol(row)
        _benchmark_start, benchmark_values = benchmark_series(benchmark_symbol)
        benchmark_available = bool(calendar and benchmark_values)
        start_index, values = _read_qlib_series(qlib_dir, etf_symbol)
        available_dates = _series_available_dates(
            calendar=calendar,
            start_index=start_index,
            values=values,
        )
        missing_price_count = sum(
            1 for value in values if value != value or value <= 0
        )
        available_window_days = [
            int(window)
            for window in windows_days
            if available_dates and len(available_dates) > int(window)
        ]
        pit_gap_reasons: list[str] = []
        if not calendar:
            pit_gap_reasons.append("calendar_missing")
        if not values:
            pit_gap_reasons.append("proxy_series_missing")
        if not benchmark_available:
            pit_gap_reasons.append("benchmark_series_missing")
        if len(available_window_days) < len(windows_days):
            pit_gap_reasons.append("insufficient_window_history")
        for reason in pit_gap_reasons:
            _increment_count(aggregate_gap_counts, reason)
        mapping_records.append(
            {
                "mapping_id": str(row.get("mapping_id") or ""),
                "mapping_version": int(row.get("mapping_version") or 1),
                "sector_name": str(row.get("sector_name") or ""),
                "status": str(row.get("status") or "primary"),
                "effective_from": str(row.get("effective_from") or ""),
                "effective_to": str(row.get("effective_to") or ""),
                "etf_symbol": etf_symbol,
                "benchmark_symbol": benchmark_symbol,
                "benchmark_source": str(
                    row.get("benchmark_source") or INDUSTRY_ETF_BENCHMARK_SOURCE
                ),
                "benchmark_family": str(
                    row.get("benchmark_family") or INDUSTRY_ETF_BENCHMARK_FAMILY
                ),
                "calendar_source": str(qlib_etf_dir),
                "earliest_price_date": available_dates[0] if available_dates else "",
                "latest_price_date": available_dates[-1] if available_dates else "",
                "latest_calendar_date": calendar[-1] if calendar else "",
                "has_20d_window": 20 in available_window_days,
                "has_60d_window": 60 in available_window_days,
                "has_120d_window": 120 in available_window_days,
                "available_window_days": available_window_days,
                "missing_price_count": missing_price_count,
                "stale_price_gap_count": missing_price_count,
                "benchmark_available": benchmark_available,
                "pit_available": not pit_gap_reasons,
                "pit_gap_reasons": pit_gap_reasons,
            }
        )
    eligible_claim_count = 0
    labelable_claim_count = 0
    labelable_window_count = 0
    pending_future_window_count = 0
    label_gap_counts: dict[str, int] = {}
    for claim in forecast_rows:
        metadata = metadata_by_source.get(str(claim.get("source_id") or "")) or {}
        if not _is_industry_research_report(metadata.get("report_type")):
            continue
        direction = str(claim.get("direction") or "unknown").lower()
        if direction not in {"positive", "negative"}:
            _increment_count(label_gap_counts, "direction_missing_or_unsupported")
            continue
        proxy = _industry_etf_proxy_for_sector(
            str(metadata.get("sector") or ""),
            mapping_rows,
            as_of_datetime=str(claim.get("signal_datetime") or ""),
        )
        if proxy is None:
            _increment_count(label_gap_counts, "sector_etf_mapping_missing")
            continue
        eligible_claim_count += 1
        if not calendar:
            _increment_count(label_gap_counts, "calendar_missing")
            continue
        entry_index = _entry_calendar_index(
            calendar,
            str(claim.get("signal_datetime") or ""),
        )
        if entry_index is None:
            _increment_count(label_gap_counts, "entry_date_after_latest_calendar")
            continue
        etf_start, etf_values = _read_qlib_series(qlib_dir, str(proxy.get("etf_symbol") or ""))
        if not etf_values:
            _increment_count(label_gap_counts, "proxy_series_missing")
            continue
        benchmark_start, benchmark_values = benchmark_series(
            _industry_mapping_benchmark_symbol(proxy)
        )
        if not benchmark_values:
            _increment_count(label_gap_counts, "benchmark_series_missing")
            continue
        if _series_value_at_calendar_index(
            start_index=etf_start,
            values=etf_values,
            calendar_index=entry_index,
        ) is None:
            _increment_count(label_gap_counts, "proxy_series_missing")
            continue
        if _series_value_at_calendar_index(
            start_index=benchmark_start,
            values=benchmark_values,
            calendar_index=entry_index,
        ) is None:
            _increment_count(label_gap_counts, "benchmark_series_missing")
            continue
        claim_window_count = 0
        for window in windows_days:
            exit_index = entry_index + int(window)
            if exit_index >= len(calendar):
                pending_future_window_count += 1
                continue
            if _series_value_at_calendar_index(
                start_index=etf_start,
                values=etf_values,
                calendar_index=exit_index,
            ) is None:
                _increment_count(label_gap_counts, "proxy_series_missing")
                continue
            if _series_value_at_calendar_index(
                start_index=benchmark_start,
                values=benchmark_values,
                calendar_index=exit_index,
            ) is None:
                _increment_count(label_gap_counts, "benchmark_series_missing")
                continue
            claim_window_count += 1
            labelable_window_count += 1
        if claim_window_count:
            labelable_claim_count += 1
    return {
        "availability_id": "RKE-REPORT-INDUSTRY-ETF-PROXY-PIT-AVAILABILITY",
        "policy": (
            "Each sector-to-ETF mapping records PIT price availability and "
            "labelability gaps before industry outcome labels are generated."
        ),
        "qlib_etf_dir_configured": str(qlib_etf_dir),
        "windows_days": [int(value) for value in windows_days],
        "mapping_count": len(mapping_records),
        "mapping_records": mapping_records,
        "pit_available_mapping_count": sum(
            1 for record in mapping_records if record["pit_available"]
        ),
        "pit_gap_counts": dict(sorted(aggregate_gap_counts.items())),
        "labelability_summary": {
            "eligible_claim_count": eligible_claim_count,
            "labelable_claim_count": labelable_claim_count,
            "labelable_window_count": labelable_window_count,
            "pending_future_window_count": pending_future_window_count,
            "sector_etf_mapping_missing_count": label_gap_counts.get(
                "sector_etf_mapping_missing",
                0,
            ),
            "proxy_series_missing_count": label_gap_counts.get(
                "proxy_series_missing",
                0,
            ),
            "benchmark_series_missing_count": label_gap_counts.get(
                "benchmark_series_missing",
                0,
            ),
            "data_gap_counts": dict(sorted(label_gap_counts.items())),
        },
    }


def build_industry_etf_proxy_readiness(
    *,
    root_path: Path,
    qlib_etf_dir: str | Path,
    forecast_rows: Sequence[Mapping[str, Any]],
    metadata_rows: Sequence[Mapping[str, Any]],
    mapping_rows: Sequence[Mapping[str, Any]] | None = None,
    pit_availability: Mapping[str, Any] | None = None,
    windows_days: Sequence[int] = INDUSTRY_ETF_PROXY_WINDOWS_DAYS,
) -> dict[str, Any]:
    mapping_rows = tuple(mapping_rows or build_default_industry_etf_proxy_map_rows())
    qlib_dir = _resolve_qlib_etf_dir(root_path, qlib_etf_dir)
    calendar = _read_trading_calendar(qlib_dir)
    benchmark_cache: dict[str, tuple[int, list[float]]] = {}

    def benchmark_series(symbol: str) -> tuple[int, list[float]]:
        benchmark_symbol = symbol or INDUSTRY_ETF_BENCHMARK_SYMBOL
        if benchmark_symbol not in benchmark_cache:
            benchmark_cache[benchmark_symbol] = _read_qlib_series(
                qlib_dir,
                benchmark_symbol,
            )
        return benchmark_cache[benchmark_symbol]

    metadata_by_source = _source_report_metadata(metadata_rows)
    eligible_claim_ids: list[str] = []
    labelable_claim_ids: list[str] = []
    data_gap_counts: dict[str, int] = {}
    labelable_window_count = 0
    pending_future_window_count = 0

    def add_gap(name: str) -> None:
        data_gap_counts[name] = data_gap_counts.get(name, 0) + 1

    for claim in forecast_rows:
        metadata = metadata_by_source.get(str(claim.get("source_id") or "")) or {}
        if not _is_industry_research_report(metadata.get("report_type")):
            continue
        direction = str(claim.get("direction") or "unknown").lower()
        if direction not in {"positive", "negative"}:
            add_gap("direction_missing_or_unsupported")
            continue
        sector = str(metadata.get("sector") or "")
        proxy = _industry_etf_proxy_for_sector(
            sector,
            mapping_rows,
            as_of_datetime=str(claim.get("signal_datetime") or ""),
        )
        if proxy is None:
            add_gap("sector_etf_mapping_missing")
            continue
        forecast_claim_id = str(claim.get("forecast_claim_id") or "")
        eligible_claim_ids.append(forecast_claim_id)
        if not calendar:
            add_gap("calendar_missing")
            continue
        benchmark_start, benchmark_values = benchmark_series(
            _industry_mapping_benchmark_symbol(proxy)
        )
        if not benchmark_values:
            add_gap("benchmark_series_missing")
            continue
        etf_symbol = str(proxy["etf_symbol"])
        etf_start, etf_values = _read_qlib_series(qlib_dir, etf_symbol)
        if not etf_values:
            add_gap("proxy_series_missing")
            continue
        entry_index = _entry_calendar_index(
            calendar,
            str(claim.get("signal_datetime") or ""),
        )
        if entry_index is None:
            add_gap("entry_date_after_latest_calendar")
            continue
        if _series_value_at_calendar_index(
            start_index=etf_start,
            values=etf_values,
            calendar_index=entry_index,
        ) is None or _series_value_at_calendar_index(
            start_index=benchmark_start,
            values=benchmark_values,
            calendar_index=entry_index,
        ) is None:
            add_gap("entry_price_missing")
            continue
        claim_labelable_window_count = 0
        for horizon_days in windows_days:
            exit_index = entry_index + int(horizon_days)
            if exit_index >= len(calendar):
                pending_future_window_count += 1
                continue
            if _series_value_at_calendar_index(
                start_index=etf_start,
                values=etf_values,
                calendar_index=exit_index,
            ) is None or _series_value_at_calendar_index(
                start_index=benchmark_start,
                values=benchmark_values,
                calendar_index=exit_index,
            ) is None:
                add_gap("exit_price_missing")
                continue
            labelable_window_count += 1
            claim_labelable_window_count += 1
        if claim_labelable_window_count:
            labelable_claim_ids.append(forecast_claim_id)
    return {
        "policy": (
            "sector-direction industry claims can be evaluated with mapped industry ETF "
            "returns on fixed PIT windows; each window is a separate evidence point; "
            "LLM output extracts the claim direction but cannot assign outcome labels"
        ),
        "outcome_label_source": INDUSTRY_ETF_OUTCOME_LABEL_SOURCE,
        "llm_outcome_labeling_allowed": False,
        "windows_days": [int(value) for value in windows_days],
        "entry_lag_trading_days": INDUSTRY_ETF_ENTRY_LAG_TRADING_DAYS,
        "benchmark_symbol": INDUSTRY_ETF_BENCHMARK_SYMBOL,
        "benchmark_symbols": sorted(
            {
                _industry_mapping_benchmark_symbol(row)
                for row in mapping_rows
                if str(row.get("status") or "primary") == "primary"
            }
        ),
        "benchmark_source": INDUSTRY_ETF_BENCHMARK_SOURCE,
        "benchmark_family": INDUSTRY_ETF_BENCHMARK_FAMILY,
        "cost_model_id": INDUSTRY_ETF_COST_MODEL_ID,
        "qlib_etf_dir_configured": str(qlib_etf_dir),
        "latest_calendar_date": calendar[-1] if calendar else "",
        "mapping_count": len(mapping_rows),
        "eligible_claim_count": len(eligible_claim_ids),
        "eligible_forecast_claim_ids": eligible_claim_ids,
        "labelable_forecast_claim_count": len(labelable_claim_ids),
        "labelable_forecast_claim_ids": labelable_claim_ids,
        "labelable_window_count": labelable_window_count,
        "pending_future_window_count": pending_future_window_count,
        "data_gap_counts": dict(sorted(data_gap_counts.items())),
        "pit_availability_status": {
            "availability_id": str(
                _ensure_mapping(pit_availability).get("availability_id") or ""
            ),
            "pit_available_mapping_count": int(
                _ensure_mapping(pit_availability).get("pit_available_mapping_count")
                or 0
            ),
            "pit_gap_counts": _ensure_mapping(
                _ensure_mapping(pit_availability).get("pit_gap_counts")
            ),
        },
    }


def build_stock_price_proxy_readiness(
    *,
    root_path: Path,
    qlib_stock_dir: str | Path,
    qlib_etf_dir: str | Path,
    forecast_rows: Sequence[Mapping[str, Any]],
    metadata_rows: Sequence[Mapping[str, Any]],
    benchmark_symbol: str = STOCK_PRICE_PROXY_BENCHMARK_SYMBOL,
    windows_days: Sequence[int] = STOCK_PRICE_PROXY_WINDOWS_DAYS,
) -> dict[str, Any]:
    stock_dir = _resolve_qlib_stock_dir(root_path, qlib_stock_dir)
    benchmark_dir = _resolve_qlib_etf_dir(root_path, qlib_etf_dir)
    stock_calendar = _read_trading_calendar(stock_dir)
    benchmark_calendar = _read_trading_calendar(benchmark_dir)
    benchmark_start, benchmark_values = _read_qlib_series(
        benchmark_dir,
        benchmark_symbol,
    )
    metadata_by_source = _source_report_metadata(metadata_rows)
    eligible_claim_ids: list[str] = []
    labelable_claim_ids: list[str] = []
    data_gap_counts: dict[str, int] = {}
    labelable_window_count = 0
    pending_future_window_count = 0

    def add_gap(name: str) -> None:
        data_gap_counts[name] = data_gap_counts.get(name, 0) + 1

    for claim in forecast_rows:
        metadata = metadata_by_source.get(str(claim.get("source_id") or "")) or {}
        if not _is_stock_forecast_claim(claim, metadata):
            continue
        forecast_claim_id = str(claim.get("forecast_claim_id") or "")
        target = _ensure_mapping(claim.get("target"))
        if str(target.get("target_type") or "").strip().lower() != "stock":
            add_gap("stock_target_mapping_missing")
            continue
        direction = str(claim.get("direction") or "unknown").lower()
        if direction not in {"positive", "negative"}:
            add_gap("direction_missing_or_unsupported")
            continue
        resolution = _stock_target_resolution(claim, metadata)
        if resolution["gap"]:
            add_gap(resolution["gap"])
            continue
        eligible_claim_ids.append(forecast_claim_id)
        ts_code = resolution["ts_code"]
        if not stock_calendar:
            add_gap("calendar_missing")
            continue
        if not benchmark_calendar or not benchmark_values:
            add_gap("benchmark_series_missing")
            continue
        stock_start, stock_values = _read_qlib_series(stock_dir, ts_code)
        if not stock_values:
            add_gap("stock_series_missing")
            continue
        volume_start, volume_values = _read_qlib_series(stock_dir, ts_code, "volume")
        open_start, open_values = _read_qlib_series(stock_dir, ts_code, "open")
        high_start, high_values = _read_qlib_series(stock_dir, ts_code, "high")
        low_start, low_values = _read_qlib_series(stock_dir, ts_code, "low")
        close_start, close_values = _read_qlib_series(stock_dir, ts_code, "close")
        if not all((volume_values, open_values, high_values, low_values, close_values)):
            add_gap("entry_liquidity_unverified")
            continue
        entry_index = _entry_calendar_index(
            stock_calendar,
            str(claim.get("signal_datetime") or ""),
        )
        if entry_index is None:
            add_gap("entry_date_after_latest_calendar")
            continue
        entry_date = stock_calendar[entry_index]
        entry_price = _series_value_at_calendar_index(
            start_index=stock_start,
            values=stock_values,
            calendar_index=entry_index,
        )
        if entry_price is None:
            add_gap("entry_price_missing")
            continue
        entry_volume_ok = _has_positive_volume_at(
            start_index=volume_start,
            values=volume_values,
            calendar_index=entry_index,
        )
        if entry_volume_ok is False:
            add_gap("stock_entry_suspended")
            continue
        if entry_volume_ok is None:
            add_gap("entry_liquidity_unverified")
            continue
        previous_close = _series_value_at_calendar_index(
            start_index=close_start,
            values=close_values,
            calendar_index=entry_index - 1,
        )
        entry_locked = _entry_limit_locked(
            direction=direction,
            previous_close=previous_close,
            open_price=_series_value_at_calendar_index(
                start_index=open_start,
                values=open_values,
                calendar_index=entry_index,
            ),
            high_price=_series_value_at_calendar_index(
                start_index=high_start,
                values=high_values,
                calendar_index=entry_index,
            ),
            low_price=_series_value_at_calendar_index(
                start_index=low_start,
                values=low_values,
                calendar_index=entry_index,
            ),
            close_price=_series_value_at_calendar_index(
                start_index=close_start,
                values=close_values,
                calendar_index=entry_index,
            ),
        )
        if entry_locked is True:
            add_gap("entry_limit_locked")
            continue
        if entry_locked is None:
            add_gap("entry_liquidity_unverified")
            continue
        if _series_value_at_date(
            calendar=benchmark_calendar,
            start_index=benchmark_start,
            values=benchmark_values,
            date_value=entry_date,
        ) is None:
            add_gap("benchmark_series_missing")
            continue
        available_dates = _series_available_dates(
            calendar=stock_calendar,
            start_index=stock_start,
            values=stock_values,
        )
        latest_stock_price_date = available_dates[-1] if available_dates else ""
        claim_labelable_window_count = 0
        for horizon_days in windows_days:
            exit_index = entry_index + int(horizon_days)
            if exit_index >= len(stock_calendar):
                pending_future_window_count += 1
                continue
            exit_date = stock_calendar[exit_index]
            exit_price = _series_value_at_calendar_index(
                start_index=stock_start,
                values=stock_values,
                calendar_index=exit_index,
            )
            if exit_price is None:
                add_gap(
                    "stock_delisted_before_exit"
                    if latest_stock_price_date and exit_date > latest_stock_price_date
                    else "exit_price_missing"
                )
                continue
            exit_volume_ok = _has_positive_volume_at(
                start_index=volume_start,
                values=volume_values,
                calendar_index=exit_index,
            )
            if exit_volume_ok is False:
                add_gap("stock_long_suspension_window")
                continue
            if exit_volume_ok is None:
                add_gap("entry_liquidity_unverified")
                continue
            exit_locked = _exit_limit_locked(
                direction=direction,
                previous_close=_series_value_at_calendar_index(
                    start_index=close_start,
                    values=close_values,
                    calendar_index=exit_index - 1,
                ),
                open_price=_series_value_at_calendar_index(
                    start_index=open_start,
                    values=open_values,
                    calendar_index=exit_index,
                ),
                high_price=_series_value_at_calendar_index(
                    start_index=high_start,
                    values=high_values,
                    calendar_index=exit_index,
                ),
                low_price=_series_value_at_calendar_index(
                    start_index=low_start,
                    values=low_values,
                    calendar_index=exit_index,
                ),
                close_price=_series_value_at_calendar_index(
                    start_index=close_start,
                    values=close_values,
                    calendar_index=exit_index,
                ),
            )
            if exit_locked is True:
                add_gap("exit_limit_locked")
                continue
            if exit_locked is None:
                add_gap("entry_liquidity_unverified")
                continue
            if _series_value_at_date(
                calendar=benchmark_calendar,
                start_index=benchmark_start,
                values=benchmark_values,
                date_value=exit_date,
            ) is None:
                add_gap("benchmark_series_missing")
                continue
            labelable_window_count += 1
            claim_labelable_window_count += 1
        if claim_labelable_window_count:
            labelable_claim_ids.append(forecast_claim_id)
    return {
        "policy": (
            "stock claims can be evaluated with qlib cn_data adjusted close "
            "returns on T+1 fixed PIT windows; LLM output extracts target and "
            "direction but cannot assign outcome labels"
        ),
        "outcome_label_source": STOCK_PRICE_PROXY_OUTCOME_LABEL_SOURCE,
        "llm_outcome_labeling_allowed": False,
        "windows_days": [int(value) for value in windows_days],
        "entry_lag_trading_days": STOCK_PRICE_PROXY_ENTRY_LAG_TRADING_DAYS,
        "benchmark_symbol": benchmark_symbol,
        "benchmark_source": STOCK_PRICE_PROXY_BENCHMARK_SOURCE,
        "benchmark_family": STOCK_PRICE_PROXY_BENCHMARK_FAMILY,
        "cost_model_id": STOCK_PRICE_PROXY_COST_MODEL_ID,
        "qlib_stock_dir_configured": str(qlib_stock_dir),
        "qlib_benchmark_dir_configured": str(qlib_etf_dir),
        "latest_calendar_date": stock_calendar[-1] if stock_calendar else "",
        "eligible_claim_count": len(eligible_claim_ids),
        "eligible_forecast_claim_ids": eligible_claim_ids,
        "labelable_forecast_claim_count": len(labelable_claim_ids),
        "labelable_forecast_claim_ids": labelable_claim_ids,
        "labelable_window_count": labelable_window_count,
        "pending_future_window_count": pending_future_window_count,
        "data_gap_counts": dict(sorted(data_gap_counts.items())),
        "pit_realism_policy": {
            "entry_suspension_blocks_label": True,
            "entry_limit_locked_blocks_label": True,
            "exit_missing_or_delisted_blocks_label": True,
            "benchmark_alignment": "date_key_cross_qlib_dir",
            "company_name_fuzzy_mapping_enabled": False,
            "survivorship_status": "survivorship_unverified",
            "survivorship_unverified": True,
            "survivorship_basis": (
                "qlib cn_data price windows observe entry and exit prices, but the "
                "local universe may exclude delisted stocks; stock proxy labels remain "
                "shadow-only until a delisted-inclusive universe audit passes"
            ),
        },
    }


def build_industry_etf_proxy_outcome_labels(
    *,
    root_path: Path,
    qlib_etf_dir: str | Path,
    forecast_rows: Sequence[Mapping[str, Any]],
    forecast_ledger_rows: Sequence[Mapping[str, Any]],
    metadata_rows: Sequence[Mapping[str, Any]],
    mapping_rows: Sequence[Mapping[str, Any]] | None = None,
    pit_availability: Mapping[str, Any] | None = None,
    windows_days: Sequence[int] = INDUSTRY_ETF_PROXY_WINDOWS_DAYS,
) -> list[dict[str, Any]]:
    mapping_rows = tuple(mapping_rows or build_default_industry_etf_proxy_map_rows())
    availability_by_mapping_id = {
        str(row.get("mapping_id") or ""): row
        for row in _ensure_list(
            _ensure_mapping(pit_availability).get("mapping_records")
        )
        if isinstance(row, Mapping)
    }
    qlib_dir = _resolve_qlib_etf_dir(root_path, qlib_etf_dir)
    calendar = _read_trading_calendar(qlib_dir)
    if not calendar:
        return []
    benchmark_cache: dict[str, tuple[int, list[float]]] = {}

    def benchmark_series(symbol: str) -> tuple[int, list[float]]:
        benchmark_symbol = symbol or INDUSTRY_ETF_BENCHMARK_SYMBOL
        if benchmark_symbol not in benchmark_cache:
            benchmark_cache[benchmark_symbol] = _read_qlib_series(
                qlib_dir,
                benchmark_symbol,
            )
        return benchmark_cache[benchmark_symbol]

    ledger_by_claim = {
        str(row.get("forecast_claim_id") or ""): row for row in forecast_ledger_rows
    }
    metadata_by_source = _source_report_metadata(metadata_rows)
    records: list[dict[str, Any]] = []
    for claim in forecast_rows:
        direction = str(claim.get("direction") or "unknown").lower()
        if direction not in {"positive", "negative"}:
            continue
        source_id = str(claim.get("source_id") or "")
        metadata = metadata_by_source.get(source_id) or {}
        if not _is_industry_research_report(metadata.get("report_type")):
            continue
        sector = str(metadata.get("sector") or "")
        proxy = _industry_etf_proxy_for_sector(
            sector,
            mapping_rows,
            as_of_datetime=str(claim.get("signal_datetime") or ""),
        )
        if proxy is None:
            continue
        etf_symbol = str(proxy["etf_symbol"])
        mapping_id = str(proxy.get("mapping_id") or "")
        mapping_availability = availability_by_mapping_id.get(mapping_id) or {}
        benchmark_symbol = _industry_mapping_benchmark_symbol(proxy)
        benchmark_start, benchmark_values = benchmark_series(benchmark_symbol)
        if not benchmark_values:
            continue
        etf_start, etf_values = _read_qlib_series(qlib_dir, etf_symbol)
        if not etf_values:
            continue
        claim_horizon = _ensure_mapping(claim.get("horizon"))
        source_horizon_days = _horizon_preferred_days(claim_horizon)
        source_horizon_bucket = _horizon_bucket(claim_horizon)
        entry_index = _entry_calendar_index(
            calendar,
            str(claim.get("signal_datetime") or ""),
        )
        if entry_index is None:
            continue
        entry_price = _series_value_at_calendar_index(
            start_index=etf_start,
            values=etf_values,
            calendar_index=entry_index,
        )
        benchmark_entry_price = _series_value_at_calendar_index(
            start_index=benchmark_start,
            values=benchmark_values,
            calendar_index=entry_index,
        )
        if entry_price is None or benchmark_entry_price is None:
            continue
        ledger = ledger_by_claim.get(str(claim.get("forecast_claim_id") or "")) or {}
        forecast_family_id = str(ledger.get("forecast_family_id") or "") or _stable_id(
            "FF",
            {
                "forecast_type": claim.get("forecast_type") or "unknown",
                "proxy_target": etf_symbol,
                "benchmark": benchmark_symbol,
            },
        )
        claim_window_set_id = _stable_id(
            "WSET",
            {
                "forecast_claim_id": claim.get("forecast_claim_id"),
                "label_type": "industry_etf_proxy",
                "etf_symbol": etf_symbol,
            },
        )
        claim_records: list[dict[str, Any]] = []
        for horizon_days in windows_days:
            exit_index = entry_index + int(horizon_days)
            if exit_index >= len(calendar):
                continue
            exit_price = _series_value_at_calendar_index(
                start_index=etf_start,
                values=etf_values,
                calendar_index=exit_index,
            )
            benchmark_exit_price = _series_value_at_calendar_index(
                start_index=benchmark_start,
                values=benchmark_values,
                calendar_index=exit_index,
            )
            if exit_price is None or benchmark_exit_price is None:
                continue
            proxy_return = exit_price / entry_price - 1.0
            benchmark_return = benchmark_exit_price / benchmark_entry_price - 1.0
            relative_alpha = proxy_return - benchmark_return
            if direction == "positive":
                directional_hit = proxy_return > 0
                relative_directional_hit = relative_alpha > 0
                directional_proxy_return = proxy_return
            else:
                directional_hit = proxy_return < 0
                relative_directional_hit = relative_alpha < 0
                directional_proxy_return = -proxy_return
            window_role = _industry_etf_window_role(int(horizon_days))
            claim_records.append(
                {
                    "outcome_id": _stable_id(
                        "OUT",
                        {
                            "forecast_claim_id": claim.get("forecast_claim_id"),
                            "label_type": "industry_etf_proxy",
                            "etf_symbol": etf_symbol,
                            "horizon_days": horizon_days,
                        },
                    ),
                    "forecast_claim_id": str(claim.get("forecast_claim_id") or ""),
                    "forecast_family_id": forecast_family_id,
                    "claim_window_set_id": claim_window_set_id,
                    "entry_datetime": f"{calendar[entry_index]}T00:00:00+08:00",
                    "exit_datetime": f"{calendar[exit_index]}T00:00:00+08:00",
                    "horizon_days": int(horizon_days),
                    "relative_alpha": round(relative_alpha, 8),
                    "directional_hit": bool(directional_hit),
                    "after_cost_alpha": round(
                        relative_alpha - INDUSTRY_ETF_ROUND_TRIP_COST,
                        8,
                    ),
                    "directional_proxy_return": round(directional_proxy_return, 8),
                    "directional_after_cost_return": round(
                        directional_proxy_return - INDUSTRY_ETF_ROUND_TRIP_COST,
                        8,
                    ),
                    "overlap_group_id": _stable_id(
                        "OVL",
                        {
                            "proxy_symbol": etf_symbol,
                            "entry_date": calendar[entry_index],
                            "horizon_days": horizon_days,
                        },
                    ),
                    "effective_n_weight": round(
                        _industry_etf_window_effective_weight(int(horizon_days)),
                        6,
                    ),
                    "pit_valid": True,
                    "survivorship_safe": True,
                    "label_type": "industry_etf_proxy",
                    "proxy_symbol": etf_symbol,
                    "proxy_label": proxy.get("mapping_label")
                    or proxy.get("etf_name")
                    or "",
                    "proxy_sector": sector,
                    "mapping_id": mapping_id,
                    "mapping_version": int(proxy.get("mapping_version") or 1),
                    "mapping_confidence": str(
                        proxy.get("mapping_confidence")
                        or "operator_seeded_exact_sector"
                    ),
                    "proxy_mapping_confidence": str(
                        proxy.get("mapping_confidence")
                        or "operator_seeded_exact_sector"
                    ),
                    "pit_availability_status": "available"
                    if mapping_availability.get("pit_available") is True
                    else "unverified",
                    "benchmark_symbol": str(
                        proxy.get("benchmark_symbol") or benchmark_symbol
                    ),
                    "benchmark_source": str(
                        proxy.get("benchmark_source") or INDUSTRY_ETF_BENCHMARK_SOURCE
                    ),
                    "benchmark_family": str(
                        proxy.get("benchmark_family") or INDUSTRY_ETF_BENCHMARK_FAMILY
                    ),
                    "cost_model_id": str(
                        proxy.get("cost_model_id") or INDUSTRY_ETF_COST_MODEL_ID
                    ),
                    "proxy_return": round(proxy_return, 8),
                    "benchmark_return": round(benchmark_return, 8),
                    "relative_directional_hit": bool(relative_directional_hit),
                    "direction_evaluated": direction,
                    "decision_basis": INDUSTRY_ETF_DECISION_BASIS,
                    "outcome_label_source": INDUSTRY_ETF_OUTCOME_LABEL_SOURCE,
                    "llm_outcome_labeling_allowed": False,
                    "performance_value_basis": "directional_after_cost_return",
                    "window_role": window_role,
                    "source_horizon_days": source_horizon_days,
                    "source_horizon_bucket": source_horizon_bucket,
                    "claim_window_alignment": _industry_etf_claim_window_alignment(
                        claim_horizon=claim_horizon,
                        horizon_days=int(horizon_days),
                    ),
                    "evaluation_policy": INDUSTRY_ETF_EVALUATION_POLICY,
                    "entry_lag_trading_days": INDUSTRY_ETF_ENTRY_LAG_TRADING_DAYS,
                    "round_trip_cost": INDUSTRY_ETF_ROUND_TRIP_COST,
                    "source_metadata_id": source_id,
                }
            )
        if claim_records:
            temporal_summary = _industry_etf_temporal_validation_summary(claim_records)
            for record in claim_records:
                record["temporal_validation_summary"] = temporal_summary
            records.extend(claim_records)
    return records


def build_stock_price_proxy_outcome_labels(
    *,
    root_path: Path,
    qlib_stock_dir: str | Path,
    qlib_etf_dir: str | Path,
    forecast_rows: Sequence[Mapping[str, Any]],
    forecast_ledger_rows: Sequence[Mapping[str, Any]],
    metadata_rows: Sequence[Mapping[str, Any]],
    benchmark_symbol: str = STOCK_PRICE_PROXY_BENCHMARK_SYMBOL,
    windows_days: Sequence[int] = STOCK_PRICE_PROXY_WINDOWS_DAYS,
) -> list[dict[str, Any]]:
    stock_dir = _resolve_qlib_stock_dir(root_path, qlib_stock_dir)
    benchmark_dir = _resolve_qlib_etf_dir(root_path, qlib_etf_dir)
    stock_calendar = _read_trading_calendar(stock_dir)
    benchmark_calendar = _read_trading_calendar(benchmark_dir)
    if not stock_calendar or not benchmark_calendar:
        return []
    benchmark_start, benchmark_values = _read_qlib_series(
        benchmark_dir,
        benchmark_symbol,
    )
    if not benchmark_values:
        return []
    ledger_by_claim = {
        str(row.get("forecast_claim_id") or ""): row for row in forecast_ledger_rows
    }
    metadata_by_source = _source_report_metadata(metadata_rows)
    records: list[dict[str, Any]] = []
    for claim in forecast_rows:
        source_id = str(claim.get("source_id") or "")
        metadata = metadata_by_source.get(source_id) or {}
        if not _is_stock_forecast_claim(claim, metadata):
            continue
        direction = str(claim.get("direction") or "unknown").lower()
        if direction not in {"positive", "negative"}:
            continue
        resolution = _stock_target_resolution(claim, metadata)
        if resolution["gap"]:
            continue
        ts_code = resolution["ts_code"]
        stock_start, stock_values = _read_qlib_series(stock_dir, ts_code)
        if not stock_values:
            continue
        volume_start, volume_values = _read_qlib_series(stock_dir, ts_code, "volume")
        open_start, open_values = _read_qlib_series(stock_dir, ts_code, "open")
        high_start, high_values = _read_qlib_series(stock_dir, ts_code, "high")
        low_start, low_values = _read_qlib_series(stock_dir, ts_code, "low")
        close_start, close_values = _read_qlib_series(stock_dir, ts_code, "close")
        if not all((volume_values, open_values, high_values, low_values, close_values)):
            continue
        entry_index = _entry_calendar_index(
            stock_calendar,
            str(claim.get("signal_datetime") or ""),
        )
        if entry_index is None:
            continue
        entry_date = stock_calendar[entry_index]
        entry_price = _series_value_at_calendar_index(
            start_index=stock_start,
            values=stock_values,
            calendar_index=entry_index,
        )
        benchmark_entry_price = _series_value_at_date(
            calendar=benchmark_calendar,
            start_index=benchmark_start,
            values=benchmark_values,
            date_value=entry_date,
        )
        if entry_price is None or benchmark_entry_price is None:
            continue
        entry_volume_ok = _has_positive_volume_at(
            start_index=volume_start,
            values=volume_values,
            calendar_index=entry_index,
        )
        if entry_volume_ok is not True:
            continue
        previous_close = _series_value_at_calendar_index(
            start_index=close_start,
            values=close_values,
            calendar_index=entry_index - 1,
        )
        entry_locked = _entry_limit_locked(
            direction=direction,
            previous_close=previous_close,
            open_price=_series_value_at_calendar_index(
                start_index=open_start,
                values=open_values,
                calendar_index=entry_index,
            ),
            high_price=_series_value_at_calendar_index(
                start_index=high_start,
                values=high_values,
                calendar_index=entry_index,
            ),
            low_price=_series_value_at_calendar_index(
                start_index=low_start,
                values=low_values,
                calendar_index=entry_index,
            ),
            close_price=_series_value_at_calendar_index(
                start_index=close_start,
                values=close_values,
                calendar_index=entry_index,
            ),
        )
        if entry_locked is not False:
            continue
        ledger = ledger_by_claim.get(str(claim.get("forecast_claim_id") or "")) or {}
        forecast_family_id = str(ledger.get("forecast_family_id") or "") or _stable_id(
            "FF",
            {
                "forecast_type": claim.get("forecast_type") or "unknown",
                "stock_target": ts_code,
                "benchmark": benchmark_symbol,
            },
        )
        claim_window_set_id = _stable_id(
            "WSET",
            {
                "forecast_claim_id": claim.get("forecast_claim_id"),
                "label_type": "stock_price_proxy",
                "stock_symbol": ts_code,
            },
        )
        claim_horizon = _ensure_mapping(claim.get("horizon"))
        source_horizon_days = _horizon_preferred_days(claim_horizon)
        source_horizon_bucket = _horizon_bucket(claim_horizon)
        target = _ensure_mapping(claim.get("target"))
        target_price_info = _stock_target_price_info(claim)
        available_dates = _series_available_dates(
            calendar=stock_calendar,
            start_index=stock_start,
            values=stock_values,
        )
        latest_stock_price_date = available_dates[-1] if available_dates else ""
        claim_records: list[dict[str, Any]] = []
        for horizon_days in windows_days:
            horizon_days = int(horizon_days)
            exit_index = entry_index + horizon_days
            if exit_index >= len(stock_calendar):
                continue
            exit_date = stock_calendar[exit_index]
            exit_price = _series_value_at_calendar_index(
                start_index=stock_start,
                values=stock_values,
                calendar_index=exit_index,
            )
            if exit_price is None:
                continue
            if latest_stock_price_date and exit_date > latest_stock_price_date:
                continue
            exit_volume_ok = _has_positive_volume_at(
                start_index=volume_start,
                values=volume_values,
                calendar_index=exit_index,
            )
            if exit_volume_ok is not True:
                continue
            exit_locked = _exit_limit_locked(
                direction=direction,
                previous_close=_series_value_at_calendar_index(
                    start_index=close_start,
                    values=close_values,
                    calendar_index=exit_index - 1,
                ),
                open_price=_series_value_at_calendar_index(
                    start_index=open_start,
                    values=open_values,
                    calendar_index=exit_index,
                ),
                high_price=_series_value_at_calendar_index(
                    start_index=high_start,
                    values=high_values,
                    calendar_index=exit_index,
                ),
                low_price=_series_value_at_calendar_index(
                    start_index=low_start,
                    values=low_values,
                    calendar_index=exit_index,
                ),
                close_price=_series_value_at_calendar_index(
                    start_index=close_start,
                    values=close_values,
                    calendar_index=exit_index,
                ),
            )
            if exit_locked is not False:
                continue
            benchmark_exit_price = _series_value_at_date(
                calendar=benchmark_calendar,
                start_index=benchmark_start,
                values=benchmark_values,
                date_value=exit_date,
            )
            if benchmark_exit_price is None:
                continue
            stock_return = exit_price / entry_price - 1.0
            benchmark_return = benchmark_exit_price / benchmark_entry_price - 1.0
            relative_alpha = stock_return - benchmark_return
            if direction == "positive":
                directional_hit = stock_return > 0
                relative_directional_hit = relative_alpha > 0
                directional_stock_return = stock_return
            else:
                directional_hit = stock_return < 0
                relative_directional_hit = relative_alpha < 0
                directional_stock_return = -stock_return
            window_role = _stock_price_proxy_window_role(horizon_days)
            record = {
                "outcome_id": _stable_id(
                    "OUT",
                    {
                        "forecast_claim_id": claim.get("forecast_claim_id"),
                        "label_type": "stock_price_proxy",
                        "stock_symbol": ts_code,
                        "horizon_days": horizon_days,
                    },
                ),
                "forecast_claim_id": str(claim.get("forecast_claim_id") or ""),
                "forecast_family_id": forecast_family_id,
                "claim_window_set_id": claim_window_set_id,
                "entry_datetime": f"{entry_date}T00:00:00+08:00",
                "exit_datetime": f"{exit_date}T00:00:00+08:00",
                "horizon_days": horizon_days,
                "relative_alpha": round(relative_alpha, 8),
                "directional_hit": bool(directional_hit),
                "after_cost_alpha": round(
                    relative_alpha - STOCK_PRICE_PROXY_ROUND_TRIP_COST,
                    8,
                ),
                "overlap_group_id": _stable_id(
                    "OVL",
                    {
                        "label_type": "stock_price_proxy",
                        "proxy_symbol": ts_code,
                        "entry_date": entry_date,
                        "horizon_days": horizon_days,
                    },
                ),
                "effective_n_weight": round(
                    _stock_price_proxy_window_effective_weight(horizon_days),
                    6,
                ),
                "pit_valid": True,
                "survivorship_safe": False,
                "label_type": "stock_price_proxy",
                "proxy_symbol": ts_code,
                "proxy_label": str(target.get("target_name") or ts_code),
                "proxy_return": round(stock_return, 8),
                "stock_return": round(stock_return, 8),
                "benchmark_symbol": benchmark_symbol,
                "benchmark_source": STOCK_PRICE_PROXY_BENCHMARK_SOURCE,
                "benchmark_family": STOCK_PRICE_PROXY_BENCHMARK_FAMILY,
                "benchmark_return": round(benchmark_return, 8),
                "benchmark_alignment": "date_key_cross_qlib_dir",
                "benchmark_calendar_source": str(qlib_etf_dir),
                "stock_calendar_source": str(qlib_stock_dir),
                "latest_calendar_date": stock_calendar[-1],
                "cost_model_id": STOCK_PRICE_PROXY_COST_MODEL_ID,
                "round_trip_cost": STOCK_PRICE_PROXY_ROUND_TRIP_COST,
                "directional_proxy_return": round(directional_stock_return, 8),
                "directional_stock_return": round(directional_stock_return, 8),
                "directional_after_cost_return": round(
                    directional_stock_return - STOCK_PRICE_PROXY_ROUND_TRIP_COST,
                    8,
                ),
                "relative_directional_hit": bool(relative_directional_hit),
                "direction_evaluated": direction,
                "decision_basis": STOCK_PRICE_PROXY_DECISION_BASIS,
                "outcome_label_source": STOCK_PRICE_PROXY_OUTCOME_LABEL_SOURCE,
                "llm_outcome_labeling_allowed": False,
                "performance_value_basis": "directional_after_cost_return",
                "window_role": window_role,
                "source_horizon_days": source_horizon_days,
                "source_horizon_bucket": source_horizon_bucket,
                "claim_window_alignment": _stock_price_claim_window_alignment(
                    claim_horizon=claim_horizon,
                    horizon_days=horizon_days,
                ),
                "evaluation_policy": STOCK_PRICE_PROXY_EVALUATION_POLICY,
                "entry_lag_trading_days": STOCK_PRICE_PROXY_ENTRY_LAG_TRADING_DAYS,
                "target_resolution_source": resolution["target_resolution_source"],
                "metadata_ts_code": resolution["metadata_ts_code"],
                "llm_target_id": resolution["llm_target_id"],
                "source_metadata_id": source_id,
                "survivorship_check": STOCK_PRICE_PROXY_SURVIVORSHIP_CHECK,
            }
            record.update(
                _stock_target_price_hit_fields(
                    target_price_info=target_price_info,
                    direction=direction,
                    entry_price=entry_price,
                    exit_price=exit_price,
                )
            )
            claim_records.append(record)
        if claim_records:
            temporal_summary = _stock_price_temporal_validation_summary(claim_records)
            for record in claim_records:
                record["temporal_validation_summary"] = temporal_summary
            records.extend(claim_records)
    return records


def build_outcome_label_records(
    *,
    root_path: Path,
    qlib_etf_dir: str | Path,
    qlib_stock_dir: str | Path,
    forecast_rows: Sequence[Mapping[str, Any]],
    forecast_ledger_rows: Sequence[Mapping[str, Any]],
    metadata_rows: Sequence[Mapping[str, Any]],
    industry_etf_proxy_map_rows: Sequence[Mapping[str, Any]] | None = None,
    industry_etf_proxy_pit_availability: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build governed PIT outcome labels for industry and stock proxy channels."""
    return [
        *build_industry_etf_proxy_outcome_labels(
            root_path=root_path,
            qlib_etf_dir=qlib_etf_dir,
            forecast_rows=forecast_rows,
            forecast_ledger_rows=forecast_ledger_rows,
            metadata_rows=metadata_rows,
            mapping_rows=industry_etf_proxy_map_rows,
            pit_availability=industry_etf_proxy_pit_availability,
        ),
        *build_stock_price_proxy_outcome_labels(
            root_path=root_path,
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
            forecast_rows=forecast_rows,
            forecast_ledger_rows=forecast_ledger_rows,
            metadata_rows=metadata_rows,
        ),
    ]


def _weighted_mean(
    values: Sequence[tuple[float, float]],
    *,
    default: float | None = None,
) -> float | None:
    weight_sum = sum(max(weight, 0.0) for _, weight in values)
    if weight_sum <= 0:
        return default
    return sum(value * max(weight, 0.0) for value, weight in values) / weight_sum


def _label_weight(label: Mapping[str, Any]) -> float:
    try:
        value = float(label.get("effective_n_weight") or 0.0)
    except (TypeError, ValueError):
        value = 0.0
    return value if value > 0 else 1.0


def _performance_reliability_bucket(n_effective: float) -> str:
    if n_effective >= 30:
        return "high_effective_n"
    if n_effective >= 10:
        return "medium_effective_n"
    if n_effective >= 3:
        return "low_effective_n"
    return "insufficient_data"


def _shrunk_performance_summary(
    labels: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    n_nominal = len(labels)
    n_effective = sum(_label_weight(label) for label in labels)
    reliability = _performance_reliability_bucket(n_effective)
    alpha_values: list[tuple[float, float]] = []
    hit_values: list[tuple[float, float]] = []
    for label in labels:
        weight = _label_weight(label)
        try:
            performance_value = (
                label.get("directional_after_cost_return")
                if label.get("performance_value_basis")
                == "directional_after_cost_return"
                else label.get("after_cost_alpha")
            )
            alpha = float(performance_value or 0.0)
        except (TypeError, ValueError):
            alpha = 0.0
        alpha_values.append((alpha, weight))
        hit_values.append((1.0 if label.get("directional_hit") is True else 0.0, weight))
    mean_alpha = _weighted_mean(alpha_values, default=None)
    hit_rate = _weighted_mean(hit_values, default=None)
    prior_n = 10.0
    shrunk_alpha = (
        (mean_alpha or 0.0) * n_effective / (n_effective + prior_n)
        if n_effective > 0
        else 0.0
    )
    shrunk_hit_rate = (
        ((hit_rate or 0.5) * n_effective + 0.5 * prior_n)
        / (n_effective + prior_n)
        if n_effective > 0
        else 0.5
    )
    if reliability == "insufficient_data":
        bucket = "insufficient_data"
        multiplier = 1.0
    elif shrunk_alpha > 0 and shrunk_hit_rate >= 0.53:
        bucket = f"positive_{reliability}"
        multiplier = {
            "low_effective_n": 1.03,
            "medium_effective_n": 1.07,
            "high_effective_n": 1.10,
        }[reliability]
    elif shrunk_alpha < 0 and shrunk_hit_rate <= 0.47:
        bucket = f"negative_{reliability}"
        multiplier = {
            "low_effective_n": 0.97,
            "medium_effective_n": 0.93,
            "high_effective_n": 0.90,
        }[reliability]
    else:
        bucket = f"neutral_{reliability}"
        multiplier = 1.0
    return {
        "n_nominal": n_nominal,
        "n_effective": round(n_effective, 6),
        "mean_after_cost_alpha": round(mean_alpha, 8) if mean_alpha is not None else None,
        "hit_rate": round(hit_rate, 6) if hit_rate is not None else None,
        "shrunk_after_cost_alpha": round(shrunk_alpha, 8),
        "shrunk_hit_rate": round(shrunk_hit_rate, 6),
        "statistical_reliability_bucket": reliability,
        "shrunk_performance_bucket": bucket,
        "weight_multiplier": multiplier,
        "insufficient_data": reliability == "insufficient_data",
    }


def _outcome_layer_key(label: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(label.get("label_type") or "standard"),
        str(label.get("benchmark_family") or "unknown_benchmark_family"),
        str(label.get("cost_model_id") or "unknown_cost_model"),
    )


def _outcome_layer_support(
    labels: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for label in labels:
        grouped.setdefault(_outcome_layer_key(label), []).append(label)
    layer_summaries: list[dict[str, Any]] = []
    for (label_type, benchmark_family, cost_model_id), rows in sorted(grouped.items()):
        summary = _shrunk_performance_summary(rows)
        layer_summaries.append(
            {
                "label_type": label_type,
                "benchmark_family": benchmark_family,
                "cost_model_id": cost_model_id,
                "n_nominal": summary["n_nominal"],
                "n_effective": summary["n_effective"],
                "mean_after_cost_alpha": summary["mean_after_cost_alpha"],
                "hit_rate": summary["hit_rate"],
                "shrunk_after_cost_alpha": summary["shrunk_after_cost_alpha"],
                "shrunk_hit_rate": summary["shrunk_hit_rate"],
                "statistical_reliability_bucket": summary[
                    "statistical_reliability_bucket"
                ],
            }
        )
    return {
        "layer_count": len(layer_summaries),
        "mixed_layer_profile": len(layer_summaries) > 1,
        "layer_keys": [
            {
                "label_type": row["label_type"],
                "benchmark_family": row["benchmark_family"],
                "cost_model_id": row["cost_model_id"],
            }
            for row in layer_summaries
        ],
        "layer_summaries": layer_summaries,
        "layering_policy": (
            "overall profile metrics are diagnostic only; compare performance by "
            "label_type, benchmark_family, and cost_model_id before interpreting "
            "alpha or hit-rate across heterogeneous proxy channels"
        ),
    }


def _labels_by_claim(
    outcome_label_rows: Sequence[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    labels: dict[str, list[Mapping[str, Any]]] = {}
    for label in outcome_label_rows:
        claim_id = str(label.get("forecast_claim_id") or "")
        if claim_id and label.get("pit_valid") is True:
            labels.setdefault(claim_id, []).append(label)
    return labels


def _viewpoint_cluster_id(claim: Mapping[str, Any]) -> tuple[str, list[str]]:
    mechanism_chain = [
        str(item)
        for item in _ensure_list(claim.get("metric_proxy_mapping"))
        if str(item).strip()
    ] or [str(claim.get("forecast_type") or "unknown")]
    return (
        _stable_id(
            "VIEW",
            {
                "mechanism_chain": mechanism_chain,
                "direction": claim.get("direction"),
                "forecast_type": claim.get("forecast_type"),
            },
        ),
        mechanism_chain,
    )


def build_source_performance_profiles(
    metadata_rows: Sequence[Mapping[str, Any]],
    *,
    forecast_rows: Sequence[Mapping[str, Any]] = (),
    outcome_label_rows: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    profile_labels: dict[str, list[Mapping[str, Any]]] = {}
    metadata_by_source = _source_report_metadata(metadata_rows)
    labels_by_claim = _labels_by_claim(outcome_label_rows)
    for claim in forecast_rows:
        claim_labels = labels_by_claim.get(str(claim.get("forecast_claim_id") or ""))
        if not claim_labels:
            continue
        row = metadata_by_source.get(str(claim.get("source_id") or "")) or {}
        for entity_type, entity_id, _ in [
            ("institution", row.get("institution_id"), row.get("institution")),
            *[
                ("author", author_id, row.get("author"))
                for author_id in _ensure_list(row.get("author_ids"))
            ],
        ]:
            if not str(entity_id or "").strip():
                continue
            profile_id = _stable_id(
                "SPP",
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "sector": row.get("sector") or "unknown",
                },
            )
            profile_labels.setdefault(profile_id, []).extend(claim_labels)
    for row in metadata_rows:
        entities = [
            ("institution", row.get("institution_id"), row.get("institution")),
            *[
                ("author", author_id, row.get("author"))
                for author_id in _ensure_list(row.get("author_ids"))
            ],
        ]
        for entity_type, entity_id, label in entities:
            if not str(entity_id or "").strip():
                continue
            profile_id = _stable_id(
                "SPP",
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "sector": row.get("sector") or "unknown",
                },
            )
            profiles.setdefault(
                profile_id,
                {
                    "profile_id": profile_id,
                    "entity_type": entity_type,
                    "entity_id": str(entity_id),
                    "entity_label": str(label or ""),
                    "context": {
                        "market": row.get("market") or "CN_A_SHARE",
                        "sector": row.get("sector") or "unknown",
                        "forecast_type": "unknown",
                        "horizon_bucket": "unknown",
                        "regime_bucket": "unknown",
                    },
                    "as_of_datetime": row.get("accessible_datetime") or "",
                    "n_nominal": 0,
                    "n_effective": 0.0,
                    "mean_after_cost_alpha": None,
                    "hit_rate": None,
                    "calibration_error": None,
                    "max_drawdown_after_signal_median": None,
                    "stability_bucket": "insufficient_data",
                    "statistical_reliability_bucket": "insufficient_data",
                    "shrunk_performance_bucket": "insufficient_data",
                    "weight_multiplier": 1.0,
                    "parent_prior_used": "global_neutral_prior",
                    "outcome_layer_support": _outcome_layer_support(()),
                    "insufficient_data": True,
                    "methodology_notes": [
                        "no_outcome_labels_yet",
                        "neutral_weight_until_pit_backtest",
                    ],
                },
            )
    for profile_id, labels in profile_labels.items():
        profile = profiles.get(profile_id)
        if profile is None:
            continue
        summary = _shrunk_performance_summary(labels)
        performance_as_of = _format_pit_datetime(
            _max_pit_datetime(labels, fields=("exit_datetime", "entry_datetime"))
        )
        profile.update(
            {
                "as_of_datetime": performance_as_of or profile.get("as_of_datetime", ""),
                "n_nominal": summary["n_nominal"],
                "n_effective": summary["n_effective"],
                "mean_after_cost_alpha": summary["mean_after_cost_alpha"],
                "hit_rate": summary["hit_rate"],
                "shrunk_after_cost_alpha": summary["shrunk_after_cost_alpha"],
                "shrunk_hit_rate": summary["shrunk_hit_rate"],
                "calibration_error": None,
                "outcome_layer_support": _outcome_layer_support(labels),
                "stability_bucket": "stable_enough_for_shadow_prior"
                if not summary["insufficient_data"]
                else "insufficient_data",
                "statistical_reliability_bucket": summary[
                    "statistical_reliability_bucket"
                ],
                "shrunk_performance_bucket": summary["shrunk_performance_bucket"],
                "weight_multiplier": summary["weight_multiplier"],
                "parent_prior_used": "global_neutral_prior_with_shrinkage",
                "insufficient_data": summary["insufficient_data"],
                "methodology_notes": [
                    "pit_outcome_labels_used",
                    "performance_as_of_after_outcome_exit",
                    "effective_n_weight_overlap_adjusted",
                    "neutral_prior_shrinkage_applied",
                    "research_prior_only_not_signal",
                ],
            }
        )
    return list(profiles.values())


def build_viewpoint_performance_profiles(
    forecast_rows: Sequence[Mapping[str, Any]],
    *,
    outcome_label_rows: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    profile_labels: dict[str, list[Mapping[str, Any]]] = {}
    labels_by_claim = _labels_by_claim(outcome_label_rows)
    for claim in forecast_rows:
        cluster_id, mechanism_chain = _viewpoint_cluster_id(claim)
        profile_id = _stable_id("VPP", {"viewpoint_cluster_id": cluster_id})
        profiles.setdefault(
            profile_id,
            {
                "viewpoint_profile_id": profile_id,
                "viewpoint_cluster_id": cluster_id,
                "mechanism_chain": mechanism_chain,
                "context": {
                    "market": "CN_A_SHARE",
                    "horizon_bucket": _horizon_bucket(_ensure_mapping(claim.get("horizon"))),
                    "regime_bucket": "unknown",
                },
                "outcome_layer_support": _outcome_layer_support(()),
                "n_effective": 0.0,
                "statistical_reliability_bucket": "insufficient_data",
                "shrunk_performance_bucket": "insufficient_data",
                "viewpoint_weight_multiplier": 1.0,
                "known_failure_modes": [
                    str(item.get("text") if isinstance(item, Mapping) else item)
                    for item in _ensure_list(claim.get("failure_modes"))
                    if str(item).strip()
                ],
                "last_revalidated_at": "",
                "insufficient_data": True,
                "methodology_notes": ["awaiting_pit_outcome_labels"],
            },
        )
        claim_labels = labels_by_claim.get(str(claim.get("forecast_claim_id") or ""))
        if claim_labels:
            profile_labels.setdefault(profile_id, []).extend(claim_labels)
    for profile_id, labels in profile_labels.items():
        profile = profiles.get(profile_id)
        if profile is None:
            continue
        summary = _shrunk_performance_summary(labels)
        performance_as_of = _format_pit_datetime(
            _max_pit_datetime(labels, fields=("exit_datetime", "entry_datetime"))
        )
        profile.update(
            {
                "n_effective": summary["n_effective"],
                "n_nominal": summary["n_nominal"],
                "hit_rate": summary["hit_rate"],
                "mean_after_cost_alpha": summary["mean_after_cost_alpha"],
                "shrunk_after_cost_alpha": summary["shrunk_after_cost_alpha"],
                "shrunk_hit_rate": summary["shrunk_hit_rate"],
                "outcome_layer_support": _outcome_layer_support(labels),
                "statistical_reliability_bucket": summary[
                    "statistical_reliability_bucket"
                ],
                "shrunk_performance_bucket": summary["shrunk_performance_bucket"],
                "viewpoint_weight_multiplier": summary["weight_multiplier"],
                "last_revalidated_at": performance_as_of or _utc_now(),
                "insufficient_data": summary["insufficient_data"],
                "methodology_notes": [
                    "pit_outcome_labels_used",
                    "performance_as_of_after_outcome_exit",
                    "effective_n_weight_overlap_adjusted",
                    "neutral_prior_shrinkage_applied",
                    "research_prior_only_not_signal",
                ],
            }
        )
    return list(profiles.values())


def build_method_performance_profiles(
    method_rows: Sequence[Mapping[str, Any]],
    *,
    outcome_label_rows: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    labels_by_method: dict[str, list[Mapping[str, Any]]] = {}
    for label in outcome_label_rows:
        if label.get("pit_valid") is not True:
            continue
        method_id = str(label.get("method_pattern_id") or "").strip()
        if method_id:
            labels_by_method.setdefault(method_id, []).append(label)
    for method in method_rows:
        method_id = str(method.get("method_pattern_id") or "")
        if not method_id:
            continue
        labels = labels_by_method.get(method_id, [])
        summary = _shrunk_performance_summary(labels)
        layer_support = _outcome_layer_support(labels)
        n_effective = summary["n_effective"]
        hit_rate = summary["hit_rate"]
        mean_alpha = summary["mean_after_cost_alpha"]
        insufficient_data = summary["insufficient_data"]
        profiles.append(
            {
                "method_profile_id": _stable_id("MPP", {"method_pattern_id": method_id}),
                "method_pattern_id": method_id,
                "context": {
                    "market": "CN_A_SHARE",
                    "agent_id": (method.get("target_agents") or ["unknown"])[0],
                    "horizon_bucket": "unknown",
                    "regime_bucket": "unknown",
                },
                "source_support": {
                    "high_weight_report_count": 0,
                    "deduped_viewpoint_count": 0,
                    "n_effective_reports": n_effective,
                    "outcome_label_row_count": summary["n_nominal"],
                },
                "outcome_layer_support": layer_support,
                "validation_status": "candidate",
                "after_cost_alpha_delta_bucket": (
                    "positive_after_cost_alpha"
                    if mean_alpha is not None and mean_alpha > 0
                    else "negative_after_cost_alpha"
                    if mean_alpha is not None and mean_alpha < 0
                    else "insufficient_data"
                ),
                "calibration_delta_bucket": (
                    "positive_hit_rate"
                    if hit_rate is not None and hit_rate >= 0.53
                    else "negative_hit_rate"
                    if hit_rate is not None and hit_rate <= 0.47
                    else "insufficient_data"
                    if hit_rate is None
                    else "neutral_hit_rate"
                ),
                "shrunk_method_priority": (
                    "candidate_with_pit_outcome_evidence"
                    if not insufficient_data
                    else "candidate_insufficient_data"
                ),
                "allowed_runtime_mode": "shadow_only",
                "insufficient_data": insufficient_data,
            }
        )
    return profiles


def build_tool_coverage_matches(
    metric_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for metric in metric_rows:
        metric_id = str(metric.get("metric_candidate_id") or "")
        canonical = str(metric.get("canonical_name") or "")
        coverage = classify_tool_coverage(canonical)
        status = str(coverage["coverage_status"])
        gaps = []
        if status == "missing":
            gaps.append("tool_missing")
        elif status != "exact_match":
            gaps.append("coverage_requires_review")
        records.append(
            {
                "coverage_id": _stable_id("COV", {"metric_candidate_id": metric_id}),
                "metric_candidate_id": metric_id,
                "coverage_status": status,
                "existing_tool_id": (coverage["existing_tool_ids"] or [""])[0],
                "existing_tool_ids": list(coverage["existing_tool_ids"]),
                "coverage_details": {
                    "raw_source_match": status == "exact_match",
                    "frequency_match": status == "exact_match",
                    "pit_available": status in {"exact_match", "partial_match", "proxy_available"},
                    "lookback_supported": status == "exact_match",
                    "unit_supported": status == "exact_match",
                    "license_ok": status != "license_blocked",
                    "historical_length_years": None,
                },
                "gaps": gaps,
                "last_checked_at": _utc_now(),
            }
        )
    return records


def _tool_name_for_metric(metric_name: str) -> str:
    canonical = _canonical_metric_name(metric_name) or "unknown_metric"
    return f"get_{canonical}_indicators"


def _tool_gap_license_status(gap: Mapping[str, Any]) -> str:
    text = " ".join(
        [
            str(gap.get("gap_type") or ""),
            *[str(item) for item in _ensure_list(gap.get("blocking_issues"))],
            *[str(item) for item in _ensure_list(gap.get("priority_reasons"))],
        ]
    ).lower()
    if "prohibited" in text or "forbidden" in text:
        return "prohibited"
    if "restricted" in text or "compliance" in text:
        return "restricted"
    return "pending_review"


def _tool_gap_pit_feasibility_status(gap: Mapping[str, Any]) -> str:
    text = " ".join(
        [
            str(gap.get("gap_type") or ""),
            *[str(item) for item in _ensure_list(gap.get("blocking_issues"))],
            *[str(item) for item in _ensure_list(gap.get("priority_reasons"))],
        ]
    ).lower()
    if "no_pit" in text or "pit_blocked" in text:
        return "pit_blocked"
    if "pit" in text or "revision" in text or "history" in text:
        return "requires_pit_backfill_review"
    return "pit_feasible_pending_vendor_review"


def _tool_gap_engineering_effort(gap: Mapping[str, Any]) -> str:
    priority = str(gap.get("priority_bucket") or "low")
    gap_type = str(gap.get("gap_type") or "").lower().replace(" ", "_")
    pit_status = _tool_gap_pit_feasibility_status(gap)
    if priority == "high" or pit_status in {"pit_blocked", "requires_pit_backfill_review"}:
        return "high"
    if "data_source" in gap_type or "data_availability" in gap_type:
        return "high"
    if priority == "medium" or _is_gap_missing_or_data_blocked(gap_type):
        return "medium"
    return "low"


def build_data_acquisition_proposals(
    tool_gap_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for gap in tool_gap_rows:
        gap_id = str(gap.get("tool_gap_id") or "")
        metric_name = str(gap.get("metric_name") or gap.get("metric_candidate_id") or "")
        if not gap_id:
            continue
        owner = str(gap.get("owner") or "data_engineering")
        license_status = _tool_gap_license_status(gap)
        pit_status = _tool_gap_pit_feasibility_status(gap)
        engineering_effort = _tool_gap_engineering_effort(gap)
        proposals.append(
            {
                "data_proposal_id": _stable_id("DAP", {"tool_gap_id": gap_id}),
                "tool_gap_id": gap_id,
                "owner": owner,
                "requested_dataset": metric_name or "unknown_dataset",
                "required_fields": ["date", "value", "source_timestamp", "quality_flags"],
                "pit_requirements": {
                    "timestamp_required": True,
                    "revision_tracking_required": True,
                    "minimum_history_years": 5,
                    "survivorship_issue": False,
                },
                "license_requirements": {
                    "internal_model_use": True,
                    "derived_metric_storage": True,
                    "external_redistribution": False,
                },
                "license_status": license_status,
                "pit_feasibility_status": pit_status,
                "expected_use_cases": _ensure_list(gap.get("target_agents"))
                or ["report_intelligence_tool_gap_resolution"],
                "estimated_engineering_effort": engineering_effort,
                "estimated_vendor_cost_bucket": "unknown",
                "business_priority": str(gap.get("priority_bucket") or "low"),
                "source_tool_gap_priority": str(gap.get("priority_bucket") or "low"),
                "decision_status": "pending_review",
            }
        )
    return proposals


def build_tool_design_proposals(
    tool_gap_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for gap in tool_gap_rows:
        gap_id = str(gap.get("tool_gap_id") or "")
        metric_name = str(gap.get("metric_name") or "unknown_metric")
        if not gap_id:
            continue
        owner = str(gap.get("owner") or "data_engineering")
        proposals.append(
            {
                "tool_proposal_id": _stable_id("TDP", {"tool_gap_id": gap_id}),
                "tool_gap_id": gap_id,
                "owner": owner,
                "tool_name_candidate": _tool_name_for_metric(metric_name),
                "target_agents": _ensure_list(gap.get("target_agents")),
                "source_tool_gap_priority": str(gap.get("priority_bucket") or "low"),
                "license_status": _tool_gap_license_status(gap),
                "pit_feasibility_status": _tool_gap_pit_feasibility_status(gap),
                "engineering_estimate": _tool_gap_engineering_effort(gap),
                "input_parameters": {
                    "market": "CN_A_SHARE",
                    "as_of_date": "date",
                    "lookback_days": 20,
                },
                "output_schema": {
                    "as_of_date": "date",
                    "metrics": [
                        {
                            "name": metric_name,
                            "value": "number",
                            "unit": "unknown",
                            "freshness_days": "integer",
                            "pit_valid": "boolean",
                            "fallback": "boolean",
                            "quality_flags": "array",
                        }
                    ],
                },
                "fallback_policy": {
                    "fallback_metric": "",
                    "confidence_cap_if_fallback": 0.60,
                },
                "validation_plan": {
                    "shadow_runtime_days": 60,
                    "primary_metric": "agent_calibration_delta",
                    "secondary_metrics": ["hit_rate_20d", "after_cost_alpha_20d"],
                    "required_effective_n": 30,
                },
                "status": "shadow_build_requested",
            }
        )
    return proposals


ANALYSIS_RECIPE_ENTRY_CONDITION = "T+1_or_more_conservative_shadow_entry"
ANALYSIS_RECIPE_EXIT_CONDITION = "fixed_horizon_shadow_exit"
ANALYSIS_RECIPE_EXPECTED_HORIZON_DAYS = 60
ANALYSIS_RECIPE_RISK_CONTROLS = (
    "no_production_order",
    "no_position_sizing",
    "after_cost_alpha_required",
    "consecutive_after_cost_decay_blocks_validation",
    "turnover_cost_decay_blocks_validation",
    "drawdown_threshold_pre_registered",
)


def _analysis_recipe_output_signal_name(name: str) -> str:
    return f"{_canonical_metric_name(name)}_score"


def build_analysis_recipes(
    method_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    recipes: list[dict[str, Any]] = []
    for method in method_rows:
        method_id = str(method.get("method_pattern_id") or "")
        name = str(method.get("name") or method_id or "unknown_method")
        if not method_id:
            continue
        recipe_id = _stable_id("RECIPE", {"method_pattern_id": method_id})
        output_signal_name = _analysis_recipe_output_signal_name(name)
        steps: list[dict[str, Any]] = []
        required_tools: list[str] = []
        for index, step in enumerate(_ensure_list(method.get("steps")), 1):
            step_text = step if isinstance(step, str) else json.dumps(_jsonable(step), ensure_ascii=False, sort_keys=True)
            metric = _canonical_metric_name(step_text) or "unknown_metric"
            coverage = classify_tool_coverage(metric)
            tool = (coverage["existing_tool_ids"] or [f"tool.requested.{metric}"])[0]
            required_tools.append(tool)
            steps.append(
                {
                    "step": index,
                    "tool": tool,
                    "metric": metric,
                    "operation": "candidate_from_report_method",
                    "interpretation": step_text,
                }
            )
        recipes.append(
            {
                "analysis_recipe_id": recipe_id,
                "recipe_id": recipe_id,
                "name": name,
                "method_pattern_id": method_id,
                "source_method_pattern_ids": [method_id],
                "version": "0.1.0",
                "promotion_state": "shadow_candidate",
                "runtime_mode": "shadow_only",
                "required_tools": list(dict.fromkeys(required_tools)),
                "required_data": _analysis_recipe_required_data(method, steps),
                "decision_scope": output_signal_name,
                "entry_condition": ANALYSIS_RECIPE_ENTRY_CONDITION,
                "exit_condition": ANALYSIS_RECIPE_EXIT_CONDITION,
                "risk_controls": list(ANALYSIS_RECIPE_RISK_CONTROLS),
                "expected_horizon_days": ANALYSIS_RECIPE_EXPECTED_HORIZON_DAYS,
                "steps": steps,
                "output_signal": {
                    "name": output_signal_name,
                    "range": [-1, 1],
                    "confidence_policy": "requires_current_data_and_validation",
                },
                "validation_status": "candidate",
                "promotion_requirements": [
                    "tool correctness tests pass",
                    "PIT backtest pass",
                    "paper trading pass",
                    "no increase in turnover-adjusted loss",
                ],
            }
        )
    return recipes


def _analysis_recipe_required_data(
    method: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]],
) -> list[str]:
    explicit = [
        str(item).strip()
        for item in _ensure_list(method.get("required_current_data"))
        if str(item).strip()
    ]
    if explicit:
        return list(dict.fromkeys(explicit))
    inferred = [
        f"metric:{str(step.get('metric')).strip()}"
        for step in steps
        if str(step.get("metric") or "").strip()
        and str(step.get("metric") or "").strip() != "unknown_metric"
    ]
    return list(dict.fromkeys(inferred))


RECIPE_PAPER_TRADING_PROTOCOL_VERSION = "recipe_shadow_paper_trading_v1"
RECIPE_PAPER_TRADING_MIN_EFFECTIVE_N = 3.0
RECIPE_PAPER_TRADING_MAX_DRAWDOWN = 0.20
RECIPE_PAPER_TRADING_ALPHA_DECAY_FAIL_STREAK = 2
RECIPE_PAPER_TRADING_MAX_HORIZON_CONCENTRATION = 0.70
RECIPE_PAPER_TRADING_MAX_REGIME_CONCENTRATION = 0.80
RECIPE_PAPER_TRADING_MIN_HORIZON_COUNT = 2
RECIPE_PAPER_TRADING_MIN_REGIME_COUNT = 2
RECIPE_PAPER_TRADING_COST_DECAY_TURNOVER_THRESHOLD = 6.0
RECIPE_PAPER_TRADING_BENCHMARK_SYMBOL = STOCK_PRICE_PROXY_BENCHMARK_SYMBOL
RECIPE_PAPER_TRADING_COST_MODEL_ID = STOCK_PRICE_PROXY_COST_MODEL_ID
CONFIDENCE_IMPACT_HIGH_DELTA_THRESHOLD = 0.02
CONFIDENCE_IMPACT_CALIBRATION_ERROR_THRESHOLD = 0.20


def _recipe_preregistration_hash(recipe: Mapping[str, Any]) -> str:
    payload = {
        "analysis_recipe_id": recipe.get("analysis_recipe_id"),
        "method_pattern_id": recipe.get("method_pattern_id"),
        "version": recipe.get("version"),
        "promotion_state": recipe.get("promotion_state"),
        "source_method_pattern_ids": _ensure_list(
            recipe.get("source_method_pattern_ids")
        ),
        "required_tools": _ensure_list(recipe.get("required_tools")),
        "required_data": _ensure_list(recipe.get("required_data")),
        "decision_scope": recipe.get("decision_scope"),
        "entry_condition": recipe.get("entry_condition"),
        "exit_condition": recipe.get("exit_condition"),
        "risk_controls": _ensure_list(recipe.get("risk_controls")),
        "expected_horizon_days": recipe.get("expected_horizon_days"),
        "steps": _ensure_list(recipe.get("steps")),
        "protocol_version": RECIPE_PAPER_TRADING_PROTOCOL_VERSION,
        "entry_rule": ANALYSIS_RECIPE_ENTRY_CONDITION,
        "exit_rule": ANALYSIS_RECIPE_EXIT_CONDITION,
        "cost_model_id": RECIPE_PAPER_TRADING_COST_MODEL_ID,
        "minimum_effective_n": RECIPE_PAPER_TRADING_MIN_EFFECTIVE_N,
        "max_drawdown": RECIPE_PAPER_TRADING_MAX_DRAWDOWN,
        "alpha_decay_fail_streak": RECIPE_PAPER_TRADING_ALPHA_DECAY_FAIL_STREAK,
        "max_horizon_contribution_share": (
            RECIPE_PAPER_TRADING_MAX_HORIZON_CONCENTRATION
        ),
        "max_regime_contribution_share": (
            RECIPE_PAPER_TRADING_MAX_REGIME_CONCENTRATION
        ),
        "minimum_horizon_count": RECIPE_PAPER_TRADING_MIN_HORIZON_COUNT,
        "minimum_regime_count": RECIPE_PAPER_TRADING_MIN_REGIME_COUNT,
        "cost_decay_turnover_threshold": (
            RECIPE_PAPER_TRADING_COST_DECAY_TURNOVER_THRESHOLD
        ),
    }
    return "sha256:" + sha256(
        json.dumps(_jsonable(payload), ensure_ascii=False, sort_keys=True).encode(
            "utf-8"
        )
    ).hexdigest()


def _labels_for_recipe(
    recipe: Mapping[str, Any],
    outcome_label_rows: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    recipe_id = str(recipe.get("analysis_recipe_id") or "")
    method_id = str(recipe.get("method_pattern_id") or "")
    labels: list[Mapping[str, Any]] = []
    for label in outcome_label_rows:
        if str(label.get("analysis_recipe_id") or "") == recipe_id:
            labels.append(label)
            continue
        if method_id and str(label.get("method_pattern_id") or "") == method_id:
            labels.append(label)
    return labels


def _weighted_contribution_shares(
    totals: Mapping[str, float],
    *,
    denominator: float | None = None,
) -> dict[str, float]:
    total = denominator if denominator is not None else sum(max(value, 0.0) for value in totals.values())
    if total is None or total <= 0:
        return {}
    return {
        key: round(max(value, 0.0) / total, 6)
        for key, value in sorted(totals.items())
        if value > 0
    }


def _directional_pre_cost_alpha(label: Mapping[str, Any]) -> float | None:
    relative_alpha = _float_or_none(label.get("relative_alpha"))
    if relative_alpha is None:
        return None
    direction = str(
        label.get("direction_evaluated") or label.get("direction") or ""
    ).strip().lower()
    if direction == "positive":
        return relative_alpha
    if direction == "negative":
        return -relative_alpha
    return None


def _paper_trading_metric_summary(
    labels: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    weighted_after_cost: list[tuple[float, float]] = []
    weighted_pre_cost: list[tuple[float, float]] = []
    weighted_cost_drag: list[tuple[float, float]] = []
    weighted_benchmark: list[tuple[float, float]] = []
    weighted_hit: list[tuple[float, float]] = []
    horizons: list[int] = []
    horizon_weight_totals: dict[str, float] = {}
    regime_weight_totals: dict[str, float] = {}
    horizon_missing_count = 0
    market_regime_missing_count = 0
    ordered = sorted(labels, key=lambda row: str(row.get("exit_datetime") or ""))
    for label in ordered:
        weight = _label_weight(label)
        after_cost = _float_or_none(label.get("directional_after_cost_return"))
        if after_cost is None:
            after_cost = _float_or_none(label.get("after_cost_alpha"))
        benchmark = _float_or_none(label.get("benchmark_return"))
        pre_cost = _directional_pre_cost_alpha(label)
        if after_cost is not None:
            weighted_after_cost.append((after_cost, weight))
        if pre_cost is not None:
            weighted_pre_cost.append((pre_cost, weight))
            if after_cost is not None:
                weighted_cost_drag.append((pre_cost - after_cost, weight))
        if benchmark is not None:
            weighted_benchmark.append((benchmark, weight))
        weighted_hit.append((1.0 if label.get("directional_hit") is True else 0.0, weight))
        horizon = _int_or_none(label.get("horizon_days"))
        if horizon:
            horizons.append(horizon)
            horizon_key = str(horizon)
            horizon_weight_totals[horizon_key] = (
                horizon_weight_totals.get(horizon_key, 0.0) + weight
            )
        else:
            horizon_missing_count += 1
        regime = str(
            label.get("market_regime") or label.get("regime") or ""
        ).strip()
        if regime:
            regime_weight_totals[regime] = regime_weight_totals.get(regime, 0.0) + weight
        else:
            market_regime_missing_count += 1
    effective_n = sum(_label_weight(label) for label in labels)
    horizon_contribution_shares = _weighted_contribution_shares(
        horizon_weight_totals,
        denominator=effective_n,
    )
    regime_contribution_shares = _weighted_contribution_shares(
        regime_weight_totals,
        denominator=effective_n,
    )
    cost_adjusted_alpha = _weighted_mean(weighted_after_cost, default=None)
    pre_cost_alpha = _weighted_mean(weighted_pre_cost, default=None)
    estimated_cost_drag = _weighted_mean(weighted_cost_drag, default=None)
    benchmark_return = _weighted_mean(weighted_benchmark, default=None)
    hit_rate = _weighted_mean(weighted_hit, default=None)
    average_horizon = sum(horizons) / len(horizons) if horizons else None
    annualized_return = (
        cost_adjusted_alpha * (252.0 / average_horizon)
        if cost_adjusted_alpha is not None and average_horizon
        else None
    )
    alpha_values = [value for value, _weight in weighted_after_cost]
    max_non_positive_streak = 0
    current_non_positive_streak = 0
    for value in alpha_values:
        if value <= 0:
            current_non_positive_streak += 1
            max_non_positive_streak = max(
                max_non_positive_streak,
                current_non_positive_streak,
            )
        else:
            current_non_positive_streak = 0
    if len(alpha_values) >= 2:
        midpoint = max(1, len(alpha_values) // 2)
        first = sum(alpha_values[:midpoint]) / len(alpha_values[:midpoint])
        second = sum(alpha_values[midpoint:]) / len(alpha_values[midpoint:])
        alpha_decay_slope = second - first
    else:
        alpha_decay_slope = None
    max_drawdown = min(alpha_values) if alpha_values else None
    sharpe = None
    if len(alpha_values) >= 2:
        mean_alpha = sum(alpha_values) / len(alpha_values)
        variance = sum((value - mean_alpha) ** 2 for value in alpha_values) / (
            len(alpha_values) - 1
        )
        if variance > 0:
            sharpe = mean_alpha / (variance**0.5)
    return {
        "annualized_return": round(annualized_return, 8)
        if annualized_return is not None
        else None,
        "benchmark_return": round(benchmark_return, 8)
        if benchmark_return is not None
        else None,
        "alpha": round(cost_adjusted_alpha, 8)
        if cost_adjusted_alpha is not None
        else None,
        "sharpe": round(sharpe, 8) if sharpe is not None else None,
        "max_drawdown": round(max_drawdown, 8) if max_drawdown is not None else None,
        "turnover": round(252.0 / average_horizon, 8) if average_horizon else None,
        "hit_rate": round(hit_rate, 6) if hit_rate is not None else None,
        "effective_n": round(effective_n, 6),
        "cost_adjusted_alpha": round(cost_adjusted_alpha, 8)
        if cost_adjusted_alpha is not None
        else None,
        "pre_cost_alpha": round(pre_cost_alpha, 8)
        if pre_cost_alpha is not None
        else None,
        "estimated_cost_drag": round(estimated_cost_drag, 8)
        if estimated_cost_drag is not None
        else None,
        "alpha_decay_slope": round(alpha_decay_slope, 8)
        if alpha_decay_slope is not None
        else None,
        "calibration_error": round(abs((hit_rate or 0.5) - 0.5), 6)
        if hit_rate is not None
        else None,
        "brier_score": round((0.5 - hit_rate) ** 2, 6)
        if hit_rate is not None
        else None,
        "non_positive_after_cost_window_streak": max_non_positive_streak,
        "horizon_contribution_shares": horizon_contribution_shares,
        "max_horizon_contribution_share": max(horizon_contribution_shares.values())
        if horizon_contribution_shares
        else None,
        "observed_horizon_count": len(horizon_contribution_shares),
        "horizon_missing_count": horizon_missing_count,
        "regime_contribution_shares": regime_contribution_shares,
        "max_regime_contribution_share": max(regime_contribution_shares.values())
        if regime_contribution_shares
        else None,
        "observed_regime_count": len(regime_contribution_shares),
        "market_regime_missing_count": market_regime_missing_count,
        "drawdown_breach_count": sum(
            1
            for value in alpha_values
            if value <= -RECIPE_PAPER_TRADING_MAX_DRAWDOWN
        ),
    }


def _method_profile_by_method_id(
    method_performance_profile_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    return {
        str(row.get("method_pattern_id") or ""): row
        for row in method_performance_profile_rows
        if str(row.get("method_pattern_id") or "").strip()
    }


def build_recipe_paper_trading_runs(
    *,
    run_id: str,
    analysis_recipe_rows: Sequence[Mapping[str, Any]],
    outcome_label_rows: Sequence[Mapping[str, Any]],
    method_performance_profile_rows: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    method_profiles = _method_profile_by_method_id(method_performance_profile_rows)
    runs: list[dict[str, Any]] = []
    for index, recipe in enumerate(analysis_recipe_rows, 1):
        recipe_id = _recipe_id(recipe, index)
        method_id = str(recipe.get("method_pattern_id") or "")
        source_method_pattern_ids = _ensure_list(
            recipe.get("source_method_pattern_ids")
        ) or ([method_id] if method_id else [])
        decision_scope = str(
            recipe.get("decision_scope")
            or _ensure_mapping(recipe.get("output_signal")).get("name")
            or ""
        )
        entry_condition = str(
            recipe.get("entry_condition") or ANALYSIS_RECIPE_ENTRY_CONDITION
        )
        exit_condition = str(
            recipe.get("exit_condition") or ANALYSIS_RECIPE_EXIT_CONDITION
        )
        risk_controls = _ensure_list(recipe.get("risk_controls")) or list(
            ANALYSIS_RECIPE_RISK_CONTROLS
        )
        expected_horizon_days = (
            _int_or_none(recipe.get("expected_horizon_days"))
            or ANALYSIS_RECIPE_EXPECTED_HORIZON_DAYS
        )
        labels = _labels_for_recipe(recipe, outcome_label_rows)
        metrics = _paper_trading_metric_summary(labels)
        blockers: list[str] = []
        if not labels:
            blockers.append("no_direct_recipe_outcome_binding")
        if float(metrics.get("effective_n") or 0.0) < RECIPE_PAPER_TRADING_MIN_EFFECTIVE_N:
            blockers.append("insufficient_effective_n")
        if any(
            str(tool).startswith("tool.requested.")
            for tool in _ensure_list(recipe.get("required_tools"))
        ):
            blockers.append("required_tools_not_shadow_implemented")
        required_data = [
            str(item).strip()
            for item in _ensure_list(recipe.get("required_data"))
            if str(item).strip()
        ]
        if not required_data:
            blockers.append("required_data_missing")
        if str(recipe.get("runtime_mode") or "") != "shadow_only":
            blockers.append("unsupported_runtime_mode")
        cost_adjusted_alpha = _float_or_none(metrics.get("cost_adjusted_alpha"))
        pre_cost_alpha = _float_or_none(metrics.get("pre_cost_alpha"))
        hit_rate = _float_or_none(metrics.get("hit_rate"))
        max_drawdown = _float_or_none(metrics.get("max_drawdown"))
        if not blockers:
            max_horizon_share = _float_or_none(
                metrics.get("max_horizon_contribution_share")
            )
            max_regime_share = _float_or_none(
                metrics.get("max_regime_contribution_share")
            )
            turnover = _float_or_none(metrics.get("turnover"))
            observed_horizon_count = int(metrics.get("observed_horizon_count") or 0)
            horizon_missing_count = int(metrics.get("horizon_missing_count") or 0)
            observed_regime_count = int(metrics.get("observed_regime_count") or 0)
            market_regime_missing_count = int(
                metrics.get("market_regime_missing_count") or 0
            )
            if horizon_missing_count:
                blockers.append("window_horizon_missing")
            if observed_horizon_count < RECIPE_PAPER_TRADING_MIN_HORIZON_COUNT:
                blockers.append("single_window_concentration")
            if (
                max_horizon_share is not None
                and max_horizon_share > RECIPE_PAPER_TRADING_MAX_HORIZON_CONCENTRATION
            ):
                blockers.append("single_window_concentration")
            if market_regime_missing_count:
                blockers.append("market_regime_missing")
            if observed_regime_count < RECIPE_PAPER_TRADING_MIN_REGIME_COUNT or (
                max_regime_share is not None
                and max_regime_share > RECIPE_PAPER_TRADING_MAX_REGIME_CONCENTRATION
            ):
                blockers.append("single_regime_concentration")
            if cost_adjusted_alpha is None or cost_adjusted_alpha <= 0:
                blockers.append("after_cost_alpha_non_positive")
            if (
                pre_cost_alpha is not None
                and pre_cost_alpha > 0
                and cost_adjusted_alpha is not None
                and cost_adjusted_alpha <= 0
                and turnover is not None
                and turnover >= RECIPE_PAPER_TRADING_COST_DECAY_TURNOVER_THRESHOLD
            ):
                blockers.append("cost_decay_fail")
            if (
                int(metrics.get("non_positive_after_cost_window_streak") or 0)
                >= RECIPE_PAPER_TRADING_ALPHA_DECAY_FAIL_STREAK
            ):
                blockers.append("consecutive_non_positive_after_cost_windows")
            if hit_rate is None or hit_rate < 0.50:
                blockers.append("hit_rate_below_threshold")
            if max_drawdown is not None and max_drawdown < -RECIPE_PAPER_TRADING_MAX_DRAWDOWN:
                blockers.append("max_drawdown_breach")
        method_profile = method_profiles.get(method_id) or {}
        profile_n = _float_or_none(
            _ensure_mapping(method_profile.get("source_support")).get(
                "n_effective_reports"
            )
        )
        profile_support_only = (profile_n or 0.0) > 0 and bool(blockers)
        status = "passed" if not blockers else "blocked"
        runs.append(
            {
                "paper_trading_run_id": _stable_id(
                    "RIPT",
                    {
                        "analysis_recipe_id": recipe_id,
                        "protocol_version": RECIPE_PAPER_TRADING_PROTOCOL_VERSION,
                    },
                ),
                "analysis_recipe_id": recipe_id,
                "experiment_id": _stable_id(
                    "RIEXP",
                    {
                        "analysis_recipe_id": recipe_id,
                        "protocol_version": RECIPE_PAPER_TRADING_PROTOCOL_VERSION,
                    },
                ),
                "pre_registration_hash": _recipe_preregistration_hash(recipe),
                "protocol_version": RECIPE_PAPER_TRADING_PROTOCOL_VERSION,
                "promotion_state": "shadow_candidate",
                "validation_status": status,
                "paper_trading_status": status,
                "source_method_pattern_ids": source_method_pattern_ids,
                "required_tools": _ensure_list(recipe.get("required_tools")),
                "required_data": required_data,
                "decision_scope": decision_scope,
                "entry_condition": entry_condition,
                "exit_condition": exit_condition,
                "risk_controls": risk_controls,
                "expected_horizon_days": expected_horizon_days,
                "benchmark_symbol": RECIPE_PAPER_TRADING_BENCHMARK_SYMBOL,
                "benchmark_source": STOCK_PRICE_PROXY_BENCHMARK_SOURCE,
                "cost_model_id": RECIPE_PAPER_TRADING_COST_MODEL_ID,
                "pre_registered_protocol": {
                    "entry_semantics": "T+1_or_more_conservative",
                    "exit_semantics": "fixed_horizon_shadow_exit",
                    "cost_model_id": RECIPE_PAPER_TRADING_COST_MODEL_ID,
                    "benchmark_symbol": RECIPE_PAPER_TRADING_BENCHMARK_SYMBOL,
                    "minimum_effective_n": RECIPE_PAPER_TRADING_MIN_EFFECTIVE_N,
                    "max_drawdown": RECIPE_PAPER_TRADING_MAX_DRAWDOWN,
                    "alpha_decay_fail_streak": (
                        RECIPE_PAPER_TRADING_ALPHA_DECAY_FAIL_STREAK
                    ),
                    "max_horizon_contribution_share": (
                        RECIPE_PAPER_TRADING_MAX_HORIZON_CONCENTRATION
                    ),
                    "max_regime_contribution_share": (
                        RECIPE_PAPER_TRADING_MAX_REGIME_CONCENTRATION
                    ),
                    "minimum_horizon_count": RECIPE_PAPER_TRADING_MIN_HORIZON_COUNT,
                    "minimum_regime_count": RECIPE_PAPER_TRADING_MIN_REGIME_COUNT,
                    "cost_decay_turnover_threshold": (
                        RECIPE_PAPER_TRADING_COST_DECAY_TURNOVER_THRESHOLD
                    ),
                    "profile_weight_is_sufficient": False,
                    "parameter_tuning_after_results_allowed": False,
                    "production_decision_impact_allowed": False,
                },
                "metrics": metrics,
                "blocked_reasons": sorted(set(blockers)),
                "profile_weight_support": {
                    "method_profile_id": method_profile.get("method_profile_id") or "",
                    "n_effective_reports": profile_n,
                    "profile_only_validation_allowed": False,
                    "profile_paper_trade_disagreement": profile_support_only,
                },
                "production_decision_impact_allowed": False,
                "policy": (
                    "analysis recipes cannot promote from profile weights alone; "
                    "paper-trading requires direct PIT outcome binding, pre-registered "
                    "T+1 protocol, after-cost alpha, effective N, and no requested-tool placeholders"
                ),
            }
        )
    return runs


def build_recipe_paper_trading_summary(
    *,
    run_id: str,
    recipe_paper_trading_runs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    blocker_counts: dict[str, int] = {}
    passed_ids: list[str] = []
    blocked_ids: list[str] = []
    disagreement_count = 0
    cost_adjusted_values: list[float] = []
    for run in recipe_paper_trading_runs:
        status = str(run.get("paper_trading_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        recipe_id = str(run.get("analysis_recipe_id") or "")
        if status == "passed":
            passed_ids.append(recipe_id)
        else:
            blocked_ids.append(recipe_id)
        for reason in _ensure_list(run.get("blocked_reasons")):
            _increment_count(blocker_counts, reason)
        profile_support = _ensure_mapping(run.get("profile_weight_support"))
        if profile_support.get("profile_paper_trade_disagreement") is True:
            disagreement_count += 1
        cost_adjusted = _float_or_none(
            _ensure_mapping(run.get("metrics")).get("cost_adjusted_alpha")
        )
        if cost_adjusted is not None:
            cost_adjusted_values.append(cost_adjusted)
    return {
        "summary_id": "RKE-REPORT-INTELLIGENCE-RECIPE-PAPER-TRADING-SUMMARY",
        "run_id": run_id,
        "as_of_datetime": _utc_now(),
        "protocol_version": RECIPE_PAPER_TRADING_PROTOCOL_VERSION,
        "recipe_count": len(recipe_paper_trading_runs),
        "paper_trading_run_count": len(recipe_paper_trading_runs),
        "validation_pass_count": len(passed_ids),
        "blocked_count": len(blocked_ids),
        "status_counts": dict(sorted(status_counts.items())),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "passed_recipe_ids": sorted(passed_ids),
        "blocked_recipe_ids": sorted(blocked_ids),
        "profile_paper_trade_disagreement_count": disagreement_count,
        "mean_cost_adjusted_alpha": round(
            sum(cost_adjusted_values) / len(cost_adjusted_values),
            8,
        )
        if cost_adjusted_values
        else None,
        "minimum_effective_n": RECIPE_PAPER_TRADING_MIN_EFFECTIVE_N,
        "pre_registration_policy": (
            "each recipe has a deterministic experiment id and pre-registration hash "
            "before any outcome metrics are evaluated"
        ),
        "validation_protocol": {
            "entry_semantics": "T+1_or_more_conservative",
            "cost_model_id": RECIPE_PAPER_TRADING_COST_MODEL_ID,
            "benchmark_symbol": RECIPE_PAPER_TRADING_BENCHMARK_SYMBOL,
            "profile_weight_is_sufficient": False,
            "production_decision_impact_allowed": False,
        },
        "policy": (
            "paper-trading validation is a shadow gate; profile support can prioritize "
            "recipes but cannot promote confidence impact without direct PIT paper-trading evidence"
        ),
    }


def build_confidence_impact_observations(
    *,
    run_id: str,
    recipe_paper_trading_runs: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for run in recipe_paper_trading_runs:
        recipe_id = str(run.get("analysis_recipe_id") or "")
        metrics = _ensure_mapping(run.get("metrics"))
        paper_status = str(run.get("paper_trading_status") or "unknown")
        after_cost_alpha = _float_or_none(metrics.get("cost_adjusted_alpha"))
        realized_alpha = _float_or_none(metrics.get("alpha"))
        alpha_decay_slope = _float_or_none(metrics.get("alpha_decay_slope"))
        calibration_error = _float_or_none(metrics.get("calibration_error"))
        brier_score = _float_or_none(metrics.get("brier_score"))
        hit_rate = _float_or_none(metrics.get("hit_rate"))
        blocker_reasons = _ensure_list(run.get("blocked_reasons"))
        alpha_decay_blockers = {
            "after_cost_alpha_non_positive",
            "consecutive_non_positive_after_cost_windows",
            "max_drawdown_breach",
        }
        cost_decay_blockers = {"cost_decay_fail"}
        regime_fragile_blockers = {
            "single_window_concentration",
            "single_regime_concentration",
            "market_regime_missing",
            "window_horizon_missing",
        }
        if paper_status != "passed" and any(
            str(reason) in cost_decay_blockers for reason in blocker_reasons
        ):
            drift_status = "cost_decay_fail"
            recommended_action = "freeze_recipe"
            confidence_delta = 0.0
        elif paper_status != "passed" and any(
            str(reason) in alpha_decay_blockers for reason in blocker_reasons
        ):
            drift_status = "alpha_decay_fail"
            recommended_action = "freeze_recipe"
            confidence_delta = 0.0
        elif paper_status != "passed" and any(
            str(reason) in regime_fragile_blockers for reason in blocker_reasons
        ):
            drift_status = "regime_fragile_alpha"
            recommended_action = "send_to_manual_review"
            confidence_delta = 0.0
        elif paper_status != "passed":
            drift_status = "paper_trading_blocked"
            recommended_action = "keep_shadow"
            confidence_delta = 0.0
        elif after_cost_alpha is not None and after_cost_alpha <= 0:
            drift_status = "alpha_decay_fail"
            recommended_action = "freeze_recipe"
            confidence_delta = 0.0
        elif alpha_decay_slope is not None and alpha_decay_slope < 0:
            drift_status = "alpha_decay_watch"
            recommended_action = "reduce_confidence_impact"
            confidence_delta = 0.0
        elif calibration_error is not None and calibration_error > 0.20:
            drift_status = "calibration_drift_watch"
            recommended_action = "send_to_manual_review"
            confidence_delta = 0.0
        else:
            drift_status = "stable_shadow"
            recommended_action = "keep_shadow"
            confidence_delta = min(0.03, max(0.0, after_cost_alpha or 0.0))
        observations.append(
            {
                "confidence_observation_id": _stable_id(
                    "CIMOBS",
                    {
                        "run_id": run_id,
                        "analysis_recipe_id": recipe_id,
                    },
                ),
                "run_id": run_id,
                "recipe_id": recipe_id,
                "agent_id": "report_intelligence.shadow",
                "confidence_delta": round(confidence_delta, 6),
                "confidence_delta_source": "recipe_paper_trading_validation",
                "expected_alpha": after_cost_alpha,
                "realized_alpha": realized_alpha,
                "after_cost_realized_alpha": after_cost_alpha,
                "pre_cost_realized_alpha": metrics.get("pre_cost_alpha"),
                "estimated_cost_drag": metrics.get("estimated_cost_drag"),
                "alpha_decay_slope": alpha_decay_slope,
                "calibration_error": calibration_error,
                "brier_score": brier_score,
                "hit_rate_recent": hit_rate,
                "hit_rate_baseline": 0.5,
                "drawdown_since_activation": metrics.get("max_drawdown"),
                "regime": "unknown",
                "paper_trading_status": paper_status,
                "drift_status": drift_status,
                "recommended_action": recommended_action,
                "blocker_reasons": blocker_reasons,
                "production_decision_impact_allowed": False,
            }
        )
    return observations


def _pearson_correlation(pairs: Sequence[tuple[float, float]]) -> float | None:
    if len(pairs) < 2:
        return None
    xs = [item[0] for item in pairs]
    ys = [item[1] for item in pairs]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    x_var = sum((value - x_mean) ** 2 for value in xs)
    y_var = sum((value - y_mean) ** 2 for value in ys)
    if x_var <= 0 or y_var <= 0:
        return None
    covariance = sum((x - x_mean) * (y - y_mean) for x, y in pairs)
    return covariance / ((x_var * y_var) ** 0.5)


def _confidence_delta_bucket(delta: float | None) -> str:
    if delta is None or delta == 0:
        return "zero"
    if delta < 0:
        return "negative"
    if delta >= CONFIDENCE_IMPACT_HIGH_DELTA_THRESHOLD:
        return "high_positive"
    return "low_positive"


def _confidence_bucket_outcome_summary(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        delta = _float_or_none(row.get("confidence_delta"))
        bucket = _confidence_delta_bucket(delta)
        item = grouped.setdefault(
            bucket,
            {
                "count": 0,
                "realized_alpha_values": [],
                "hit_rate_values": [],
            },
        )
        item["count"] += 1
        realized_alpha = _float_or_none(
            row.get("after_cost_realized_alpha")
            if row.get("after_cost_realized_alpha") is not None
            else row.get("realized_alpha")
        )
        hit_rate = _float_or_none(row.get("hit_rate_recent"))
        if realized_alpha is not None:
            item["realized_alpha_values"].append(realized_alpha)
        if hit_rate is not None:
            item["hit_rate_values"].append(hit_rate)
    summary: dict[str, dict[str, Any]] = {}
    for bucket, item in grouped.items():
        alpha_values = item["realized_alpha_values"]
        hit_values = item["hit_rate_values"]
        summary[bucket] = {
            "count": int(item["count"]),
            "mean_realized_alpha": round(sum(alpha_values) / len(alpha_values), 8)
            if alpha_values
            else None,
            "mean_hit_rate": round(sum(hit_values) / len(hit_values), 6)
            if hit_values
            else None,
        }
    return dict(sorted(summary.items()))


def _is_new_regime_observation(row: Mapping[str, Any]) -> bool:
    if row.get("regime_is_new") is True:
        return True
    regime_status = str(row.get("regime_status") or "").strip().lower()
    return regime_status in {"new", "new_regime", "unseen_regime"}


def build_confidence_impact_monitor(
    *,
    run_id: str,
    confidence_observation_rows: Sequence[Mapping[str, Any]],
    recipe_paper_trading_summary: Mapping[str, Any],
) -> dict[str, Any]:
    drift_status_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    blocker_counts: dict[str, int] = {}
    tracked_recipe_ids: list[str] = []
    alpha_decay_recipe_ids: list[str] = []
    cost_decay_recipe_ids: list[str] = []
    calibration_drift_recipe_ids: list[str] = []
    regime_fragile_recipe_ids: list[str] = []
    manual_review_recipe_ids: list[str] = []
    freeze_recipe_ids: list[str] = []
    retire_recipe_ids: list[str] = []
    unvalidated_impact_count = 0
    confidence_alpha_pairs: list[tuple[float, float]] = []
    confidence_alpha_pair_recipe_ids: list[str] = []
    calibration_rule_counts: dict[str, int] = {}
    aggregate_calibration_recipe_ids: list[str] = []
    new_regime_miscalibration_recipe_ids: list[str] = []
    for row in confidence_observation_rows:
        _increment_count(drift_status_counts, row.get("drift_status"))
        _increment_count(action_counts, row.get("recommended_action"))
        recipe_id = str(row.get("recipe_id") or "")
        if recipe_id:
            tracked_recipe_ids.append(recipe_id)
        confidence_delta = _float_or_none(row.get("confidence_delta"))
        realized_alpha = _float_or_none(
            row.get("after_cost_realized_alpha")
            if row.get("after_cost_realized_alpha") is not None
            else row.get("realized_alpha")
        )
        hit_rate_recent = _float_or_none(row.get("hit_rate_recent"))
        hit_rate_baseline = _float_or_none(row.get("hit_rate_baseline"))
        calibration_error = _float_or_none(row.get("calibration_error"))
        if confidence_delta is not None and realized_alpha is not None:
            confidence_alpha_pairs.append((confidence_delta, realized_alpha))
            if recipe_id:
                confidence_alpha_pair_recipe_ids.append(recipe_id)
        if (
            confidence_delta is not None
            and confidence_delta > 0
            and hit_rate_recent is not None
            and hit_rate_baseline is not None
            and hit_rate_recent <= hit_rate_baseline
        ):
            _increment_count(
                calibration_rule_counts,
                "positive_confidence_hit_nonimprovement",
            )
            if recipe_id:
                aggregate_calibration_recipe_ids.append(recipe_id)
        if (
            confidence_delta is not None
            and confidence_delta >= CONFIDENCE_IMPACT_HIGH_DELTA_THRESHOLD
            and (
                (realized_alpha is not None and realized_alpha <= 0)
                or (
                    hit_rate_recent is not None
                    and hit_rate_baseline is not None
                    and hit_rate_recent < hit_rate_baseline
                )
            )
        ):
            _increment_count(
                calibration_rule_counts,
                "high_confidence_underperformance",
            )
            if recipe_id:
                aggregate_calibration_recipe_ids.append(recipe_id)
        if _is_new_regime_observation(row) and (
            (
                calibration_error is not None
                and calibration_error > CONFIDENCE_IMPACT_CALIBRATION_ERROR_THRESHOLD
            )
            or (
                hit_rate_recent is not None
                and hit_rate_baseline is not None
                and hit_rate_recent < hit_rate_baseline
            )
            or (realized_alpha is not None and realized_alpha <= 0)
        ):
            _increment_count(calibration_rule_counts, "new_regime_miscalibration")
            if recipe_id:
                aggregate_calibration_recipe_ids.append(recipe_id)
                new_regime_miscalibration_recipe_ids.append(recipe_id)
        if str(row.get("drift_status") or "") in {
            "alpha_decay_watch",
            "alpha_decay_fail",
        } and recipe_id:
            alpha_decay_recipe_ids.append(recipe_id)
        if str(row.get("drift_status") or "") == "cost_decay_fail" and recipe_id:
            cost_decay_recipe_ids.append(recipe_id)
        if str(row.get("drift_status") or "") == "calibration_drift_watch" and recipe_id:
            calibration_drift_recipe_ids.append(recipe_id)
        if str(row.get("drift_status") or "") == "regime_fragile_alpha" and recipe_id:
            regime_fragile_recipe_ids.append(recipe_id)
        action = str(row.get("recommended_action") or "")
        if action == "send_to_manual_review" and recipe_id:
            manual_review_recipe_ids.append(recipe_id)
        if action == "freeze_recipe" and recipe_id:
            freeze_recipe_ids.append(recipe_id)
        if action == "retire_recipe" and recipe_id:
            retire_recipe_ids.append(recipe_id)
        if (
            row.get("paper_trading_status") != "passed"
            and (_float_or_none(row.get("confidence_delta")) or 0.0) != 0.0
        ):
            unvalidated_impact_count += 1
        for reason in _ensure_list(row.get("blocker_reasons")):
            _increment_count(blocker_counts, reason)
    confidence_alpha_correlation = _pearson_correlation(confidence_alpha_pairs)
    if confidence_alpha_correlation is not None and confidence_alpha_correlation < 0:
        _increment_count(
            calibration_rule_counts,
            "negative_confidence_alpha_correlation",
        )
        aggregate_calibration_recipe_ids.extend(confidence_alpha_pair_recipe_ids)
    aggregate_calibration_recipe_ids = sorted(set(aggregate_calibration_recipe_ids))
    calibration_drift_recipe_ids.extend(aggregate_calibration_recipe_ids)
    manual_review_recipe_ids.extend(aggregate_calibration_recipe_ids)
    return {
        "monitor_id": "RKE-REPORT-INTELLIGENCE-CONFIDENCE-IMPACT-MONITOR",
        "run_id": run_id,
        "as_of_datetime": _utc_now(),
        "recipe_count": int(recipe_paper_trading_summary.get("recipe_count") or 0),
        "observation_count": len(confidence_observation_rows),
        "paper_trading_validated_recipe_count": int(
            recipe_paper_trading_summary.get("validation_pass_count") or 0
        ),
        "blocked_recipe_count": int(
            recipe_paper_trading_summary.get("blocked_count") or 0
        ),
        "unvalidated_confidence_impact_count": unvalidated_impact_count,
        "alpha_decay_watch_count": drift_status_counts.get("alpha_decay_watch", 0),
        "alpha_decay_fail_count": drift_status_counts.get("alpha_decay_fail", 0),
        "cost_decay_fail_count": drift_status_counts.get("cost_decay_fail", 0),
        "calibration_drift_count": drift_status_counts.get(
            "calibration_drift_watch",
            0,
        ),
        "aggregate_calibration_drift_count": sum(calibration_rule_counts.values()),
        "regime_fragile_alpha_count": drift_status_counts.get(
            "regime_fragile_alpha",
            0,
        ),
        "confidence_alpha_correlation": round(confidence_alpha_correlation, 8)
        if confidence_alpha_correlation is not None
        else None,
        "confidence_alpha_correlation_status": (
            "negative"
            if confidence_alpha_correlation is not None
            and confidence_alpha_correlation < 0
            else "non_negative"
            if confidence_alpha_correlation is not None
            else "insufficient_data"
        ),
        "confidence_delta_bucket_outcomes": _confidence_bucket_outcome_summary(
            confidence_observation_rows
        ),
        "calibration_drift_rule_counts": dict(
            sorted(calibration_rule_counts.items())
        ),
        "drift_status_counts": dict(sorted(drift_status_counts.items())),
        "recommended_action_counts": dict(sorted(action_counts.items())),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "tracked_recipe_ids": sorted(set(tracked_recipe_ids)),
        "alpha_decay_recipe_ids": sorted(set(alpha_decay_recipe_ids)),
        "cost_decay_recipe_ids": sorted(set(cost_decay_recipe_ids)),
        "calibration_drift_recipe_ids": sorted(set(calibration_drift_recipe_ids)),
        "aggregate_calibration_drift_recipe_ids": aggregate_calibration_recipe_ids,
        "new_regime_miscalibration_recipe_ids": sorted(
            set(new_regime_miscalibration_recipe_ids)
        ),
        "regime_fragile_recipe_ids": sorted(set(regime_fragile_recipe_ids)),
        "manual_review_recipe_ids": sorted(set(manual_review_recipe_ids)),
        "freeze_recipe_ids": sorted(set(freeze_recipe_ids)),
        "retire_recipe_ids": sorted(set(retire_recipe_ids)),
        "production_decision_impact_allowed": False,
        "lockbox_required_before_production_impact": True,
        "policy": (
            "confidence impact remains shadow-only; paper-trading validation, "
            "alpha-decay checks, calibration drift checks, and lockbox gates are "
            "required before any production confidence change"
        ),
    }


def write_report_intelligence_recipe_paper_trading_artifacts(
    registry_dir: str | Path,
    *,
    run_id: str = "RIR-RECIPE-PAPER-TRADING",
) -> dict[str, str]:
    registry_path = Path(registry_dir)
    blockers: list[str] = []
    analysis_recipe_rows = _read_registry_jsonl(
        registry_path / "analysis_recipes.jsonl",
        label="analysis_recipes",
        blockers=blockers,
    )
    method_performance_profile_rows = _read_registry_jsonl(
        registry_path / "method_performance_profiles.jsonl",
        label="method_performance_profiles",
        blockers=blockers,
    )
    outcome_label_path = registry_path / "report_outcome_labels.jsonl"
    outcome_label_rows: list[Mapping[str, Any]] = []
    if outcome_label_path.exists():
        outcome_label_rows = _read_registry_jsonl(
            outcome_label_path,
            label="report_outcome_labels",
            blockers=blockers,
        )
    recipe_paper_trading_run_rows = build_recipe_paper_trading_runs(
        run_id=run_id,
        analysis_recipe_rows=analysis_recipe_rows,
        outcome_label_rows=outcome_label_rows,
        method_performance_profile_rows=method_performance_profile_rows,
    )
    recipe_paper_trading_summary = build_recipe_paper_trading_summary(
        run_id=run_id,
        recipe_paper_trading_runs=recipe_paper_trading_run_rows,
    )
    confidence_impact_observation_rows = build_confidence_impact_observations(
        run_id=run_id,
        recipe_paper_trading_runs=recipe_paper_trading_run_rows,
    )
    confidence_impact_monitor = build_confidence_impact_monitor(
        run_id=run_id,
        confidence_observation_rows=confidence_impact_observation_rows,
        recipe_paper_trading_summary=recipe_paper_trading_summary,
    )
    if blockers:
        recipe_paper_trading_summary = dict(recipe_paper_trading_summary)
        recipe_paper_trading_summary["load_blockers"] = blockers
        confidence_impact_monitor = dict(confidence_impact_monitor)
        confidence_impact_monitor["load_blockers"] = blockers
    return {
        "recipe_paper_trading_runs": str(
            _write_jsonl(
                registry_path / "recipe_paper_trading_runs.jsonl",
                recipe_paper_trading_run_rows,
            )["path"]
        ),
        "recipe_paper_trading_summary": str(
            _write_json(
                registry_path / "recipe_paper_trading_summary.json",
                recipe_paper_trading_summary,
            )["path"]
        ),
        "confidence_impact_observations": str(
            _write_jsonl(
                registry_path / "confidence_impact_observations.jsonl",
                confidence_impact_observation_rows,
            )["path"]
        ),
        "confidence_impact_monitor": str(
            _write_json(
                registry_path / "confidence_impact_monitor.json",
                confidence_impact_monitor,
            )["path"]
        ),
    }


def _evolution_gate_check(
    *,
    check_id: str,
    requirement: str,
    passed: bool,
    evidence: Mapping[str, Any],
    blockers: Sequence[str],
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "requirement": requirement,
        "passed": bool(passed),
        "evidence": dict(evidence),
        "blockers": [str(item) for item in blockers if str(item).strip()],
    }


def _monitor_refresh_record_passed(row: Mapping[str, Any]) -> bool:
    if "accepted" in row:
        return row.get("accepted") is True
    blocker_counts = _count_mapping_values(_ensure_mapping(row.get("blocker_counts")))
    return (
        int(row.get("blocked_recipe_count") or 0) == 0
        and int(row.get("unvalidated_confidence_impact_count") or 0) == 0
        and int(row.get("alpha_decay_fail_count") or 0) == 0
        and int(row.get("calibration_drift_count") or 0) == 0
        and not blocker_counts
    )


def _audit_refresh_record_passed(row: Mapping[str, Any]) -> bool:
    if "accepted" in row:
        return row.get("accepted") is True
    return all(
        row.get(field) is True
        for field in (
            "schema_accepted",
            "pit_accepted",
            "provenance_accepted",
            "statistical_accepted",
        )
    )


def _trailing_pass_count(rows: Sequence[Mapping[str, Any]], *, kind: str) -> int:
    count = 0
    for row in reversed(list(rows)):
        passed = (
            _monitor_refresh_record_passed(row)
            if kind == "monitor"
            else _audit_refresh_record_passed(row)
        )
        if not passed:
            break
        count += 1
    return count


def _gap_distribution_record_stable(row: Mapping[str, Any]) -> bool:
    if "stable" in row:
        return row.get("stable") is True
    if "accepted" in row:
        return row.get("accepted") is True
    max_gap_share = _float_or_none(row.get("max_gap_share"))
    return max_gap_share is not None and max_gap_share <= 0.80


def _trailing_gap_distribution_stable_count(
    rows: Sequence[Mapping[str, Any]],
) -> int:
    count = 0
    for row in reversed(list(rows)):
        if not _gap_distribution_record_stable(row):
            break
        count += 1
    return count


def _read_evolution_history_rows(path: Path) -> list[Mapping[str, Any]]:
    if not path.exists():
        return []
    rows, parse_blockers = load_jsonl_with_errors(path, label=str(path))
    if parse_blockers:
        return []
    return [row for row in rows if isinstance(row, Mapping)]


def _append_evolution_history_record(
    rows: Sequence[Mapping[str, Any]],
    record: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    run_id = str(record.get("run_id") or "")
    deduped = [
        dict(row)
        for row in rows
        if str(row.get("run_id") or "") != run_id
    ]
    deduped.append(dict(record))
    return deduped[-EVOLUTION_REFRESH_HISTORY_MAX_ROWS:]


def _monitor_refresh_history_record(
    *,
    run_id: str,
    confidence_impact_monitor: Mapping[str, Any],
) -> dict[str, Any]:
    monitor = _ensure_mapping(confidence_impact_monitor)
    return {
        "history_id": _stable_id("MONHIST", {"run_id": run_id}),
        "history_type": "confidence_impact_monitor",
        "run_id": run_id,
        "as_of_datetime": _utc_now(),
        "accepted": _monitor_refresh_record_passed(monitor),
        "observation_count": int(monitor.get("observation_count") or 0),
        "blocked_recipe_count": int(monitor.get("blocked_recipe_count") or 0),
        "unvalidated_confidence_impact_count": int(
            monitor.get("unvalidated_confidence_impact_count") or 0
        ),
        "alpha_decay_fail_count": int(monitor.get("alpha_decay_fail_count") or 0),
        "calibration_drift_count": int(monitor.get("calibration_drift_count") or 0),
        "blocker_counts": _count_mapping_values(
            _ensure_mapping(monitor.get("blocker_counts"))
        ),
        "private_text_included": False,
    }


def _audit_refresh_history_record(
    *,
    run_id: str,
    audit_record: Mapping[str, Any],
) -> dict[str, Any]:
    audit = _ensure_mapping(audit_record)
    return {
        "history_id": _stable_id("AUDHIST", {"run_id": run_id}),
        "history_type": "schema_pit_provenance_statistical_audit",
        "run_id": run_id,
        "as_of_datetime": _utc_now(),
        "accepted": _audit_refresh_record_passed(audit),
        "schema_accepted": audit.get("schema_accepted") is True,
        "pit_accepted": audit.get("pit_accepted") is True,
        "provenance_accepted": audit.get("provenance_accepted") is True,
        "statistical_accepted": audit.get("statistical_accepted") is True,
        "private_text_included": False,
    }


def _gap_distribution_history_record(
    *,
    run_id: str,
    outcome_labeling_readiness: Mapping[str, Any],
) -> dict[str, Any]:
    gap_counts = _count_mapping_values(
        _ensure_mapping(
            _ensure_mapping(outcome_labeling_readiness).get("mapping_gap_counts")
        )
    )
    total_gap_count = sum(gap_counts.values())
    max_gap_name = ""
    max_gap_share = 0.0
    if total_gap_count:
        max_gap_name, max_gap_count = max(gap_counts.items(), key=lambda item: item[1])
        max_gap_share = max_gap_count / total_gap_count
    stable = total_gap_count == 0 or max_gap_share <= 0.80
    return {
        "history_id": _stable_id("GAPHIST", {"run_id": run_id}),
        "history_type": "mapping_gap_distribution",
        "run_id": run_id,
        "as_of_datetime": _utc_now(),
        "accepted": stable,
        "stable": stable,
        "gap_counts": gap_counts,
        "total_gap_count": total_gap_count,
        "max_gap_name": max_gap_name,
        "max_gap_share": round(max_gap_share, 6),
        "private_text_included": False,
    }


def _prepare_evolution_refresh_history(
    *,
    registry_dir: Path,
    run_id: str,
    confidence_impact_monitor: Mapping[str, Any],
    schema_validation_report: Mapping[str, Any],
    pit_leakage_audit: Mapping[str, Any],
    extraction_provenance_audit: Mapping[str, Any],
    statistical_robustness_audit: Mapping[str, Any],
    outcome_labeling_readiness: Mapping[str, Any],
) -> dict[str, list[Mapping[str, Any]]]:
    monitor_history_rows = _read_evolution_history_rows(
        registry_dir / "monitor_refresh_history.jsonl"
    )
    audit_history_rows = _read_evolution_history_rows(
        registry_dir / "audit_refresh_history.jsonl"
    )
    gap_distribution_history_rows = _read_evolution_history_rows(
        registry_dir / "gap_distribution_history.jsonl"
    )
    audit_record = _audit_current_record(
        schema_validation_report=schema_validation_report,
        pit_leakage_audit=pit_leakage_audit,
        extraction_provenance_audit=extraction_provenance_audit,
        statistical_robustness_audit=statistical_robustness_audit,
    )
    return {
        "monitor_previous": monitor_history_rows,
        "audit_previous": audit_history_rows,
        "gap_previous": gap_distribution_history_rows,
        "monitor_updated": _append_evolution_history_record(
            monitor_history_rows,
            _monitor_refresh_history_record(
                run_id=run_id,
                confidence_impact_monitor=confidence_impact_monitor,
            ),
        ),
        "audit_updated": _append_evolution_history_record(
            audit_history_rows,
            _audit_refresh_history_record(
                run_id=run_id,
                audit_record=audit_record,
            ),
        ),
        "gap_updated": _append_evolution_history_record(
            gap_distribution_history_rows,
            _gap_distribution_history_record(
                run_id=run_id,
                outcome_labeling_readiness=outcome_labeling_readiness,
            ),
        ),
    }


def _audit_current_record(
    *,
    schema_validation_report: Mapping[str, Any] | None,
    pit_leakage_audit: Mapping[str, Any],
    extraction_provenance_audit: Mapping[str, Any],
    statistical_robustness_audit: Mapping[str, Any],
) -> dict[str, Any]:
    schema = _ensure_mapping(schema_validation_report)
    return {
        "schema_accepted": schema.get("accepted") is True,
        "pit_accepted": _ensure_mapping(pit_leakage_audit).get("accepted") is True,
        "provenance_accepted": (
            _ensure_mapping(extraction_provenance_audit).get("accepted") is True
        ),
        "statistical_accepted": (
            _ensure_mapping(statistical_robustness_audit).get("accepted") is True
        ),
    }


def build_report_intelligence_evolution_readiness_gate(
    *,
    run_id: str,
    forecast_rows: Sequence[Mapping[str, Any]],
    outcome_label_rows: Sequence[Mapping[str, Any]],
    recipe_paper_trading_summary: Mapping[str, Any],
    confidence_impact_monitor: Mapping[str, Any],
    markdown_coverage_summary: Mapping[str, Any],
    pit_leakage_audit: Mapping[str, Any],
    extraction_provenance_audit: Mapping[str, Any],
    statistical_robustness_audit: Mapping[str, Any],
    gold_review_summary: Mapping[str, Any],
    outcome_labeling_readiness: Mapping[str, Any] | None = None,
    schema_validation_report: Mapping[str, Any] | None = None,
    monitor_refresh_history_rows: Sequence[Mapping[str, Any]] = (),
    audit_refresh_history_rows: Sequence[Mapping[str, Any]] = (),
    gap_distribution_history_rows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    outcome_claim_ids = {
        str(row.get("forecast_claim_id") or "")
        for row in outcome_label_rows
        if str(row.get("forecast_claim_id") or "").strip()
    }
    stock_claim_ids = {
        str(row.get("forecast_claim_id") or "")
        for row in outcome_label_rows
        if str(row.get("label_type") or "") == "stock_price_proxy"
        and str(row.get("forecast_claim_id") or "").strip()
    }
    industry_claim_ids = {
        str(row.get("forecast_claim_id") or "")
        for row in outcome_label_rows
        if str(row.get("label_type") or "") == "industry_etf_proxy"
        and str(row.get("forecast_claim_id") or "").strip()
    }
    checks: list[dict[str, Any]] = []

    outcome_blockers: list[str] = []
    if len(outcome_claim_ids) < EVOLUTION_GATE_MIN_UNIQUE_OUTCOME_CLAIMS:
        outcome_blockers.append("unique_outcome_claim_count_below_threshold")
    if len(stock_claim_ids) < EVOLUTION_GATE_MIN_STOCK_PROXY_CLAIMS:
        outcome_blockers.append("stock_proxy_claim_count_below_threshold")
    if len(industry_claim_ids) < EVOLUTION_GATE_MIN_INDUSTRY_PROXY_CLAIMS:
        outcome_blockers.append("industry_proxy_claim_count_below_threshold")
    checks.append(
        _evolution_gate_check(
            check_id="RI-EVOL-01",
            requirement=(
                "Evolution requires enough stock and industry PIT outcome "
                "coverage before prompt mutation candidates can influence prompts."
            ),
            passed=not outcome_blockers,
            evidence={
                "forecast_claim_count": len(forecast_rows),
                "unique_outcome_claim_count": len(outcome_claim_ids),
                "stock_proxy_unique_claim_count": len(stock_claim_ids),
                "industry_proxy_unique_claim_count": len(industry_claim_ids),
            },
            blockers=outcome_blockers,
        )
    )

    paper_summary = _ensure_mapping(recipe_paper_trading_summary)
    paper_blockers: list[str] = []
    if int(paper_summary.get("validation_pass_count") or 0) < (
        EVOLUTION_GATE_MIN_PAPER_TRADING_RECIPES
    ):
        paper_blockers.append("paper_trading_validated_recipe_count_below_threshold")
    if int(paper_summary.get("paper_trading_run_count") or 0) < (
        EVOLUTION_GATE_MIN_PAPER_TRADING_RECIPES
    ):
        paper_blockers.append("paper_trading_run_count_below_threshold")
    if _float_or_none(paper_summary.get("mean_cost_adjusted_alpha")) is None:
        paper_blockers.append("after_cost_paper_trading_summary_missing")
    checks.append(
        _evolution_gate_check(
            check_id="RI-EVOL-02",
            requirement=(
                "At least 20 pre-registered recipes need passed after-cost "
                "paper-trading before evolution can use recipe evidence."
            ),
            passed=not paper_blockers,
            evidence={
                "paper_trading_run_count": int(
                    paper_summary.get("paper_trading_run_count") or 0
                ),
                "validation_pass_count": int(
                    paper_summary.get("validation_pass_count") or 0
                ),
                "mean_cost_adjusted_alpha": paper_summary.get(
                    "mean_cost_adjusted_alpha"
                ),
            },
            blockers=paper_blockers,
        )
    )

    monitor = _ensure_mapping(confidence_impact_monitor)
    monitor_records = [
        *[dict(row) for row in monitor_refresh_history_rows],
        dict(monitor),
    ]
    monitor_trailing_pass_count = _trailing_pass_count(
        monitor_records,
        kind="monitor",
    )
    monitor_blockers: list[str] = []
    if not _monitor_refresh_record_passed(monitor):
        monitor_blockers.append("confidence_impact_monitor_current_blocked")
    if monitor_trailing_pass_count < EVOLUTION_GATE_MIN_CONSECUTIVE_MONITOR_REFRESHES:
        monitor_blockers.append("confidence_impact_monitor_history_below_threshold")
    checks.append(
        _evolution_gate_check(
            check_id="RI-EVOL-03",
            requirement=(
                "Confidence impact monitor must be blocker-free for three "
                "consecutive refreshes before evolution can change prompts."
            ),
            passed=not monitor_blockers,
            evidence={
                "monitor_observation_count": int(
                    monitor.get("observation_count") or 0
                ),
                "blocked_recipe_count": int(monitor.get("blocked_recipe_count") or 0),
                "unvalidated_confidence_impact_count": int(
                    monitor.get("unvalidated_confidence_impact_count") or 0
                ),
                "trailing_monitor_pass_count": monitor_trailing_pass_count,
            },
            blockers=monitor_blockers,
        )
    )

    current_audit_record = _audit_current_record(
        schema_validation_report=schema_validation_report,
        pit_leakage_audit=pit_leakage_audit,
        extraction_provenance_audit=extraction_provenance_audit,
        statistical_robustness_audit=statistical_robustness_audit,
    )
    audit_records = [
        *[dict(row) for row in audit_refresh_history_rows],
        current_audit_record,
    ]
    audit_trailing_pass_count = _trailing_pass_count(audit_records, kind="audit")
    audit_blockers: list[str] = []
    if not _audit_refresh_record_passed(current_audit_record):
        audit_blockers.append("current_schema_or_audit_gate_blocked")
    if audit_trailing_pass_count < EVOLUTION_GATE_MIN_CONSECUTIVE_AUDIT_REFRESHES:
        audit_blockers.append("audit_refresh_history_below_threshold")
    checks.append(
        _evolution_gate_check(
            check_id="RI-EVOL-04",
            requirement=(
                "The last three derived refreshes must pass schema, PIT, "
                "provenance, and statistical robustness gates."
            ),
            passed=not audit_blockers,
            evidence={
                **current_audit_record,
                "trailing_audit_pass_count": audit_trailing_pass_count,
            },
            blockers=audit_blockers,
        )
    )

    gold = _ensure_mapping(gold_review_summary)
    gold_passed = gold.get("passed") is True or gold.get("accepted") is True
    gold_blockers = [] if gold_passed else ["forecast_gold_set_gate_not_passed"]
    checks.append(
        _evolution_gate_check(
            check_id="RI-EVOL-05",
            requirement=(
                "Manual forecast gold-set review must pass before prompt "
                "evolution uses extracted target, direction, or horizon signals."
            ),
            passed=gold_passed,
            evidence={
                "gold_set_passed": gold_passed,
                "reviewed_claims": int(gold.get("reviewed_claims") or 0),
                "pending_claims": int(gold.get("pending_claims") or 0),
            },
            blockers=gold_blockers,
        )
    )

    readiness = _ensure_mapping(outcome_labeling_readiness)
    current_gap_counts = _count_mapping_values(
        _ensure_mapping(readiness.get("mapping_gap_counts"))
    )
    current_gap_record = _gap_distribution_history_record(
        run_id=run_id,
        outcome_labeling_readiness=readiness,
    )
    gap_records = [
        *[dict(row) for row in gap_distribution_history_rows],
        current_gap_record,
    ]
    gap_trailing_stable_count = _trailing_gap_distribution_stable_count(gap_records)
    gap_blockers: list[str] = []
    if gap_trailing_stable_count < EVOLUTION_GATE_MIN_GAP_DISTRIBUTION_REFRESHES:
        gap_blockers.append("gap_distribution_history_below_threshold")
    checks.append(
        _evolution_gate_check(
            check_id="RI-EVOL-06",
            requirement=(
                "Outcome and missing-gap distributions must be stable across "
                "recent refreshes before evolution changes prompts."
            ),
            passed=not gap_blockers,
            evidence={
                "trailing_gap_distribution_stable_count": gap_trailing_stable_count,
                "current_mapping_gap_counts": current_gap_counts,
            },
            blockers=gap_blockers,
        )
    )

    markdown = _ensure_mapping(markdown_coverage_summary)
    coverage_blockers = [
        str(item)
        for item in _ensure_list(markdown.get("coverage_gate_blockers"))
        if str(item).strip()
    ]
    coverage_passed = str(markdown.get("coverage_gate_status") or "") == "passed"
    checks.append(
        _evolution_gate_check(
            check_id="RI-EVOL-07",
            requirement=(
                "Markdown coverage must pass P9 corpus thresholds before "
                "evolution depends on report-derived Markdown evidence."
            ),
            passed=str(markdown.get("coverage_gate_status") or "") == "passed",
            evidence={
                "coverage_gate_status": str(markdown.get("coverage_gate_status") or ""),
                "coverage_gate_blockers": coverage_blockers,
                "coverage_targets": _ensure_mapping(markdown.get("coverage_targets")),
            },
            blockers=[] if coverage_passed else (
                coverage_blockers or ["markdown_coverage_gate_not_passed"]
            ),
        )
    )

    blockers = [
        blocker
        for check in checks
        for blocker in _ensure_list(check.get("blockers"))
    ]
    return {
        "gate_id": "RKE-REPORT-INTELLIGENCE-EVOLUTION-READINESS-GATE",
        "run_id": run_id,
        "as_of_datetime": _utc_now(),
        "gate_status": "passed" if not blockers else "blocked",
        "promotion_state": (
            "ready_for_shadow_evolution_candidate"
            if not blockers
            else "blocked_before_prompt_evolution"
        ),
        "production_prompt_change_allowed": False,
        "thresholds": {
            "min_unique_outcome_claims": EVOLUTION_GATE_MIN_UNIQUE_OUTCOME_CLAIMS,
            "min_stock_proxy_claims": EVOLUTION_GATE_MIN_STOCK_PROXY_CLAIMS,
            "min_industry_proxy_claims": EVOLUTION_GATE_MIN_INDUSTRY_PROXY_CLAIMS,
            "min_paper_trading_recipes": EVOLUTION_GATE_MIN_PAPER_TRADING_RECIPES,
            "min_consecutive_monitor_refreshes": (
                EVOLUTION_GATE_MIN_CONSECUTIVE_MONITOR_REFRESHES
            ),
            "min_consecutive_audit_refreshes": (
                EVOLUTION_GATE_MIN_CONSECUTIVE_AUDIT_REFRESHES
            ),
            "min_gap_distribution_refreshes": (
                EVOLUTION_GATE_MIN_GAP_DISTRIBUTION_REFRESHES
            ),
        },
        "checks": checks,
        "blockers": sorted(set(blockers)),
        "blocker_count": len(set(blockers)),
        "private_text_included": False,
        "policy": (
            "Prompt and agent evolution remains blocked until governed aggregate "
            "PIT outcome coverage, paper-trading, monitor stability, audit history, "
            "gold-set quality, gap stability, and Markdown coverage gates pass; this "
            "artifact stores aggregate evidence only and cannot change production prompts."
        ),
    }


PROMPT_MUTATION_CANDIDATE_SCHEMA_VERSION = "prompt_mutation_candidate_v1"


def _count_mapping_values(mapping: Mapping[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key, value in mapping.items():
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count > 0:
            counts[str(key)] = count
    return counts


def _add_prompt_mutation_candidate(
    candidates: list[dict[str, Any]],
    *,
    run_id: str,
    candidate_type: str,
    target_scope: str,
    target_component: str,
    proposed_change: str,
    trigger_sources: Sequence[str],
    evidence_refs: Sequence[Mapping[str, Any]],
    severity: str = "medium",
    blocked_by: Sequence[str] = (),
) -> None:
    evidence = [dict(item) for item in evidence_refs]
    payload = {
        "candidate_type": candidate_type,
        "target_scope": target_scope,
        "target_component": target_component,
        "evidence_refs": evidence,
    }
    candidate_id = _stable_id("PMUT", payload)
    if any(row.get("mutation_candidate_id") == candidate_id for row in candidates):
        return
    candidates.append(
        {
            "mutation_candidate_id": candidate_id,
            "run_id": run_id,
            "schema_version": PROMPT_MUTATION_CANDIDATE_SCHEMA_VERSION,
            "candidate_type": candidate_type,
            "target_scope": target_scope,
            "target_component": target_component,
            "proposed_change": proposed_change,
            "trigger_sources": list(dict.fromkeys(str(item) for item in trigger_sources)),
            "evidence_refs": evidence,
            "severity": severity,
            "validation_requirements": [
                "gold_set_review_pass",
                "pit_outcome_replay_pass",
                "schema_validation_pass",
                "provenance_audit_pass",
                "statistical_robustness_audit_pass",
                "shadow_paper_trading_pass",
            ],
            "blocked_by": list(dict.fromkeys(str(item) for item in blocked_by))
            or ["gold_set_gate_pending", "paper_trading_gate_pending"],
            "promotion_state": "shadow_candidate_only",
            "manual_review_required": True,
            "production_prompt_change_allowed": False,
            "private_text_included": False,
            "policy": (
                "Prompt mutation candidates are derived from governed aggregate "
                "evidence only; they do not modify production prompts and cannot "
                "include private source content, retrieval locators, or private "
                "prompt content."
            ),
        }
    )


def _paper_trading_blocker_counts(
    recipe_paper_trading_runs: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for run in recipe_paper_trading_runs:
        for reason in _ensure_list(run.get("blocked_reasons")):
            _increment_count(counts, reason)
    return counts


def _outcome_coverage_counts(
    outcome_label_rows: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    unique_claim_ids: set[str] = set()
    stock_claim_ids: set[str] = set()
    industry_claim_ids: set[str] = set()
    for row in outcome_label_rows:
        claim_id = str(row.get("forecast_claim_id") or "").strip()
        if not claim_id:
            continue
        unique_claim_ids.add(claim_id)
        label_type = str(row.get("label_type") or "")
        if label_type == "stock_price_proxy":
            stock_claim_ids.add(claim_id)
        elif label_type == "industry_etf_proxy":
            industry_claim_ids.add(claim_id)
    return {
        "unique_outcome_claim_count": len(unique_claim_ids),
        "stock_proxy_unique_claim_count": len(stock_claim_ids),
        "industry_proxy_unique_claim_count": len(industry_claim_ids),
    }


def _evolution_gate_check_by_id(
    evolution_readiness_gate: Mapping[str, Any],
    check_id: str,
) -> dict[str, Any]:
    gate = _ensure_mapping(evolution_readiness_gate)
    for row in _ensure_list(gate.get("checks")):
        if isinstance(row, Mapping) and str(row.get("check_id") or "") == check_id:
            return dict(row)
    return {}


def _top_tool_gap_ids(
    tool_gap_rows: Sequence[Mapping[str, Any]],
    *,
    limit: int = 10,
) -> list[str]:
    priority_rank = {"urgent": 0, "blocked": 1, "high": 2, "medium": 3, "low": 4}
    ordered = sorted(
        tool_gap_rows,
        key=lambda row: (
            priority_rank.get(str(row.get("priority_bucket") or "low"), 9),
            str(row.get("tool_gap_id") or ""),
        ),
    )
    return [
        str(row.get("tool_gap_id") or "")
        for row in ordered[:limit]
        if str(row.get("tool_gap_id") or "").strip()
    ]


def build_prompt_mutation_candidates(
    *,
    run_id: str,
    outcome_labeling_readiness: Mapping[str, Any],
    tool_gap_rows: Sequence[Mapping[str, Any]],
    recipe_paper_trading_runs: Sequence[Mapping[str, Any]],
    confidence_impact_observation_rows: Sequence[Mapping[str, Any]],
    confidence_impact_monitor: Mapping[str, Any],
    markdown_coverage_summary: Mapping[str, Any],
    industry_etf_proxy_pit_availability: Mapping[str, Any],
    forecast_rows: Sequence[Mapping[str, Any]] = (),
    outcome_label_rows: Sequence[Mapping[str, Any]] = (),
    evolution_readiness_gate: Mapping[str, Any] | None = None,
    gold_review_summary: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    readiness = _ensure_mapping(outcome_labeling_readiness)
    evolution_gate = _ensure_mapping(evolution_readiness_gate)
    gate_thresholds = _ensure_mapping(evolution_gate.get("thresholds"))
    stock_readiness = _ensure_mapping(readiness.get("stock_price_proxy_readiness"))
    industry_readiness = _ensure_mapping(
        readiness.get("industry_etf_proxy_readiness")
    )
    stock_gap_counts = _count_mapping_values(
        _ensure_mapping(stock_readiness.get("data_gap_counts"))
    )
    industry_gap_counts = _count_mapping_values(
        _ensure_mapping(industry_readiness.get("data_gap_counts"))
    )
    mapping_gap_counts = _count_mapping_values(
        _ensure_mapping(readiness.get("mapping_gap_counts"))
    )
    outcome_counts = _outcome_coverage_counts(outcome_label_rows)
    outcome_threshold_gaps = {
        "unique_outcome_claim_count": max(
            EVOLUTION_GATE_MIN_UNIQUE_OUTCOME_CLAIMS
            - outcome_counts["unique_outcome_claim_count"],
            0,
        ),
        "stock_proxy_unique_claim_count": max(
            EVOLUTION_GATE_MIN_STOCK_PROXY_CLAIMS
            - outcome_counts["stock_proxy_unique_claim_count"],
            0,
        ),
        "industry_proxy_unique_claim_count": max(
            EVOLUTION_GATE_MIN_INDUSTRY_PROXY_CLAIMS
            - outcome_counts["industry_proxy_unique_claim_count"],
            0,
        ),
    }
    if any(outcome_threshold_gaps.values()):
        _add_prompt_mutation_candidate(
            candidates,
            run_id=run_id,
            candidate_type="outcome_coverage_expansion_rule",
            target_scope="report_intelligence.pit_outcome_coverage",
            target_component="report_selection_and_outcome_labeling",
            proposed_change=(
                "Expand private report selection, stock proxy evaluation, and "
                "industry ETF proxy evaluation until the evolution gate has at "
                "least 100 unique outcome claims with 30 stock and 30 industry "
                "proxy claims."
            ),
            trigger_sources=[
                "evolution_readiness_gate",
                "outcome_labeling_readiness",
                "report_outcome_labels",
            ],
            evidence_refs=[
                {
                    "artifact_path": "registry/report_intelligence/evolution_readiness_gate.json",
                    "field": "checks.RI-EVOL-01.evidence",
                    "forecast_claim_count": len(forecast_rows),
                    **outcome_counts,
                    "thresholds": {
                        "min_unique_outcome_claims": (
                            EVOLUTION_GATE_MIN_UNIQUE_OUTCOME_CLAIMS
                        ),
                        "min_stock_proxy_claims": (
                            EVOLUTION_GATE_MIN_STOCK_PROXY_CLAIMS
                        ),
                        "min_industry_proxy_claims": (
                            EVOLUTION_GATE_MIN_INDUSTRY_PROXY_CLAIMS
                        ),
                    },
                    "threshold_gaps": outcome_threshold_gaps,
                }
            ],
            severity="high",
            blocked_by=[
                "p9_markdown_coverage_target_pending",
                "stock_and_industry_outcome_replay_required",
                "manual_gold_set_gate_pending",
            ],
        )
    gold = _ensure_mapping(gold_review_summary)
    gold_check = _evolution_gate_check_by_id(evolution_gate, "RI-EVOL-05")
    gold_check_evidence = _ensure_mapping(gold_check.get("evidence"))
    gold_check_blockers = [
        str(item)
        for item in _ensure_list(gold_check.get("blockers"))
        if str(item).strip()
    ]
    gold_passed = (
        gold_check.get("passed") is True
        if gold_check
        else gold.get("passed") is True or gold.get("accepted") is True
    )
    if gold_check_blockers or (gold and not gold_passed):
        gold_evidence_source = gold_check_evidence if gold_check else gold
        _add_prompt_mutation_candidate(
            candidates,
            run_id=run_id,
            candidate_type="forecast_gold_set_review_rule",
            target_scope="report_intelligence.manual_gold_set_gate",
            target_component="forecast_gold_set_review_queue",
            proposed_change=(
                "Complete manual forecast gold-set review for target, direction, "
                "horizon, and source-grounding precision before using extracted "
                "signals for prompt evolution."
            ),
            trigger_sources=[
                "evolution_readiness_gate",
                "gold_set_review_summary",
            ],
            evidence_refs=[
                {
                    "artifact_path": (
                        "registry/report_intelligence/evolution_readiness_gate.json"
                        if gold_check
                        else "registry/gold_sets/tushare_research_reports.review_summary.json"
                    ),
                    "field": (
                        "checks.RI-EVOL-05.evidence"
                        if gold_check
                        else "forecast_gold_set_gate"
                    ),
                    "gold_set_passed": gold_passed,
                    "reviewed_claims": int(
                        gold_evidence_source.get("reviewed_claims") or 0
                    ),
                    "pending_claims": int(
                        gold_evidence_source.get("pending_claims") or 0
                    ),
                    "blockers": gold_check_blockers,
                }
            ],
            severity="high",
            blocked_by=[
                "manual_forecast_gold_set_review_required",
                "private_review_import_required",
            ],
        )
    stability_checks = [
        _evolution_gate_check_by_id(evolution_gate, "RI-EVOL-03"),
        _evolution_gate_check_by_id(evolution_gate, "RI-EVOL-04"),
        _evolution_gate_check_by_id(evolution_gate, "RI-EVOL-06"),
    ]
    stability_evidence_refs: list[dict[str, Any]] = []
    stability_blockers: list[str] = []
    for check in stability_checks:
        if not check:
            continue
        check_blockers = [
            str(item)
            for item in _ensure_list(check.get("blockers"))
            if str(item).strip()
        ]
        if not check_blockers:
            continue
        check_id = str(check.get("check_id") or "")
        stability_blockers.extend(check_blockers)
        stability_evidence_refs.append(
            {
                "artifact_path": "registry/report_intelligence/evolution_readiness_gate.json",
                "field": f"checks.{check_id}.evidence",
                "check_id": check_id,
                "blockers": check_blockers,
                "evidence": _ensure_mapping(check.get("evidence")),
                "thresholds": {
                    key: gate_thresholds.get(key)
                    for key in (
                        "min_consecutive_monitor_refreshes",
                        "min_consecutive_audit_refreshes",
                        "min_gap_distribution_refreshes",
                    )
                    if key in gate_thresholds
                },
            }
        )
    if stability_evidence_refs:
        severe_blockers = {
            "confidence_impact_monitor_current_blocked",
            "current_schema_or_audit_gate_blocked",
        }
        _add_prompt_mutation_candidate(
            candidates,
            run_id=run_id,
            candidate_type="evolution_refresh_stability_rule",
            target_scope="report_intelligence.evolution_refresh_stability",
            target_component="derived_refresh_history_gate",
            proposed_change=(
                "Accumulate three consecutive clean derived refreshes with "
                "blocker-free confidence monitor, schema/PIT/provenance/"
                "statistical audits, and stable gap distributions before prompt "
                "evolution can leave shadow candidate status."
            ),
            trigger_sources=[
                "evolution_readiness_gate",
                "monitor_refresh_history",
                "audit_refresh_history",
                "gap_distribution_history",
            ],
            evidence_refs=stability_evidence_refs,
            severity=(
                "high"
                if any(item in severe_blockers for item in stability_blockers)
                else "medium"
            ),
            blocked_by=[
                "three_clean_refreshes_required",
                "monitor_audit_gap_history_required",
            ],
        )
    target_gap_keys = (
        "stock_target_mapping_missing",
        "stock_target_missing",
        "stock_target_conflict",
    )
    target_gap_count = sum(stock_gap_counts.get(key, 0) for key in target_gap_keys)
    if target_gap_count:
        _add_prompt_mutation_candidate(
            candidates,
            run_id=run_id,
            candidate_type="target_mapping_rule",
            target_scope="report_intelligence.stock_target_binding",
            target_component="forecast_extraction_prompt",
            proposed_change=(
                "Tighten stock target extraction so ts_code, metadata ts_code, "
                "and source-grounded target_type=stock evidence are emitted only "
                "when they agree; route conflicts and name-only targets to gaps."
            ),
            trigger_sources=[
                "stock_price_proxy_readiness",
                "outcome_labeling_readiness",
            ],
            evidence_refs=[
                {
                    "artifact_path": "registry/report_intelligence/outcome_labeling_readiness.json",
                    "field": "stock_price_proxy_readiness.data_gap_counts",
                    "gap_counts": {
                        key: stock_gap_counts.get(key, 0)
                        for key in target_gap_keys
                        if stock_gap_counts.get(key, 0)
                    },
                    "total_gap_count": target_gap_count,
                }
            ],
            severity="high" if stock_gap_counts.get("stock_target_conflict", 0) else "medium",
            blocked_by=[
                "manual_gold_set_target_review_required",
                "stock_target_conflict_review_required",
            ],
        )
    horizon_direction_gap_count = sum(
        mapping_gap_counts.get(key, 0)
        + stock_gap_counts.get(key, 0)
        + industry_gap_counts.get(key, 0)
        for key in ("direction_missing_or_unsupported", "horizon", "unknown_mapping_gap")
    )
    if horizon_direction_gap_count:
        _add_prompt_mutation_candidate(
            candidates,
            run_id=run_id,
            candidate_type="horizon_direction_rule",
            target_scope="report_intelligence.forecast_mapping",
            target_component="forecast_extraction_prompt",
            proposed_change=(
                "Add stricter extraction instructions for direction and horizon "
                "normalization; ambiguous direction or horizon must remain a gap "
                "instead of becoming a testable forecast."
            ),
            trigger_sources=[
                "outcome_labeling_readiness",
                "stock_price_proxy_readiness",
                "industry_etf_proxy_readiness",
            ],
            evidence_refs=[
                {
                    "artifact_path": "registry/report_intelligence/outcome_labeling_readiness.json",
                    "field": "mapping_gap_counts",
                    "gap_counts": mapping_gap_counts,
                    "total_gap_count": horizon_direction_gap_count,
                }
            ],
            severity="medium",
        )
    industry_pit = _ensure_mapping(industry_etf_proxy_pit_availability)
    pit_gap_counts = _count_mapping_values(_ensure_mapping(industry_pit.get("pit_gap_counts")))
    sector_gap_count = industry_gap_counts.get("sector_etf_mapping_missing", 0)
    if sector_gap_count or pit_gap_counts:
        _add_prompt_mutation_candidate(
            candidates,
            run_id=run_id,
            candidate_type="industry_proxy_mapping_rule",
            target_scope="report_intelligence.industry_etf_proxy_mapping",
            target_component="industry_mapping_registry",
            proposed_change=(
                "Prioritize missing or PIT-unavailable sector mappings for "
                "operator review before using industry ETF proxy labels."
            ),
            trigger_sources=[
                "industry_etf_proxy_readiness",
                "industry_etf_proxy_pit_availability",
            ],
            evidence_refs=[
                {
                    "artifact_path": "registry/report_intelligence/industry_etf_proxy_pit_availability.json",
                    "field": "pit_gap_counts",
                    "gap_counts": pit_gap_counts,
                },
                {
                    "artifact_path": "registry/report_intelligence/outcome_labeling_readiness.json",
                    "field": "industry_etf_proxy_readiness.data_gap_counts",
                    "sector_etf_mapping_missing_count": sector_gap_count,
                },
            ],
            severity="medium",
            blocked_by=["operator_mapping_review_required"],
        )
    priority_counts: dict[str, int] = {}
    for gap in tool_gap_rows:
        _increment_count(priority_counts, gap.get("priority_bucket"))
    actionable_tool_gap_count = priority_counts.get("urgent", 0) + priority_counts.get(
        "blocked",
        0,
    ) + priority_counts.get("high", 0) + priority_counts.get("medium", 0)
    if actionable_tool_gap_count:
        _add_prompt_mutation_candidate(
            candidates,
            run_id=run_id,
            candidate_type="tool_gap_prioritization_rule",
            target_scope="report_intelligence.tool_gap_loop",
            target_component="tool_gap_prioritization_policy",
            proposed_change=(
                "Promote high and medium report-derived tool gaps into the "
                "engineering queue only after PIT, license, and required-field "
                "requirements are explicit."
            ),
            trigger_sources=["tool_gaps", "data_acquisition_proposals"],
            evidence_refs=[
                {
                    "artifact_path": "registry/report_intelligence/tool_gaps.jsonl",
                    "field": "priority_bucket",
                    "priority_counts": dict(sorted(priority_counts.items())),
                    "top_tool_gap_ids": _top_tool_gap_ids(tool_gap_rows),
                }
            ],
            severity="medium",
            blocked_by=["data_engineering_review_required"],
        )
    paper_blocker_counts = _paper_trading_blocker_counts(recipe_paper_trading_runs)
    if paper_blocker_counts:
        _add_prompt_mutation_candidate(
            candidates,
            run_id=run_id,
            candidate_type="recipe_paper_trading_rule",
            target_scope="report_intelligence.analysis_recipe_validation",
            target_component="analysis_recipe_prompt_and_tool_contract",
            proposed_change=(
                "Require analysis recipes to expose direct PIT outcome bindings, "
                "implemented tools, and pre-registered T+1 paper-trading evidence "
                "before any confidence impact is considered."
            ),
            trigger_sources=[
                "recipe_paper_trading_runs",
                "confidence_impact_monitor",
            ],
            evidence_refs=[
                {
                    "artifact_path": "registry/report_intelligence/recipe_paper_trading_runs.jsonl",
                    "field": "blocked_reasons",
                    "blocker_counts": dict(sorted(paper_blocker_counts.items())),
                }
            ],
            severity="high"
            if paper_blocker_counts.get("required_tools_not_shadow_implemented", 0)
            else "medium",
            blocked_by=["paper_trading_validation_required"],
        )
    paper_run_count = len(recipe_paper_trading_runs)
    paper_pass_count = sum(
        1
        for run in recipe_paper_trading_runs
        if str(run.get("paper_trading_status") or "") == "passed"
    )
    if (
        paper_run_count < EVOLUTION_GATE_MIN_PAPER_TRADING_RECIPES
        or paper_pass_count < EVOLUTION_GATE_MIN_PAPER_TRADING_RECIPES
    ):
        _add_prompt_mutation_candidate(
            candidates,
            run_id=run_id,
            candidate_type="recipe_paper_trading_expansion_rule",
            target_scope="report_intelligence.analysis_recipe_validation",
            target_component="pre_registered_recipe_paper_trading_queue",
            proposed_change=(
                "Increase the pre-registered recipe paper-trading queue until "
                "at least 20 recipes have direct PIT evidence, after-cost "
                "summaries, and passed validation."
            ),
            trigger_sources=[
                "recipe_paper_trading_runs",
                "recipe_paper_trading_summary",
                "evolution_readiness_gate",
            ],
            evidence_refs=[
                {
                    "artifact_path": "registry/report_intelligence/recipe_paper_trading_summary.json",
                    "field": "paper_trading_run_count.validation_pass_count",
                    "paper_trading_run_count": paper_run_count,
                    "validation_pass_count": paper_pass_count,
                    "thresholds": {
                        "min_paper_trading_recipes": (
                            EVOLUTION_GATE_MIN_PAPER_TRADING_RECIPES
                        )
                    },
                    "threshold_gaps": {
                        "paper_trading_run_count": max(
                            EVOLUTION_GATE_MIN_PAPER_TRADING_RECIPES
                            - paper_run_count,
                            0,
                        ),
                        "validation_pass_count": max(
                            EVOLUTION_GATE_MIN_PAPER_TRADING_RECIPES
                            - paper_pass_count,
                            0,
                        ),
                    },
                }
            ],
            severity="high",
            blocked_by=[
                "direct_pit_outcome_binding_required",
                "paper_trading_validation_required",
            ],
        )
    drift_counts = _count_mapping_values(
        _ensure_mapping(confidence_impact_monitor.get("drift_status_counts"))
    )
    calibration_rule_counts = _count_mapping_values(
        _ensure_mapping(confidence_impact_monitor.get("calibration_drift_rule_counts"))
    )
    drift_gap_count = sum(
        drift_counts.get(key, 0)
        for key in (
            "alpha_decay_watch",
            "alpha_decay_fail",
            "calibration_drift_watch",
            "cost_decay_fail",
            "regime_fragile_alpha",
        )
    ) + sum(calibration_rule_counts.values())
    if drift_gap_count:
        _add_prompt_mutation_candidate(
            candidates,
            run_id=run_id,
            candidate_type="calibration_fix_required",
            target_scope="report_intelligence.confidence_impact",
            target_component="confidence_calibration_policy",
            proposed_change=(
                "Reduce or freeze confidence impact for recipes with alpha decay, "
                "cost decay, calibration drift, or single-regime fragility until "
                "new shadow evidence and manual review pass."
            ),
            trigger_sources=["confidence_impact_observations"],
            evidence_refs=[
                {
                    "artifact_path": "registry/report_intelligence/confidence_impact_monitor.json",
                    "field": "drift_status_counts",
                    "drift_status_counts": drift_counts,
                    "calibration_drift_rule_counts": calibration_rule_counts,
                    "confidence_alpha_correlation": confidence_impact_monitor.get(
                        "confidence_alpha_correlation"
                    ),
                    "confidence_alpha_correlation_status": (
                        confidence_impact_monitor.get(
                            "confidence_alpha_correlation_status"
                        )
                    ),
                }
            ],
            severity="high",
            blocked_by=[
                "manual_calibration_review_required",
                "shadow_regime_and_cost_replay_required",
            ],
        )
    blocked_confidence_count = sum(
        1
        for row in confidence_impact_observation_rows
        if str(row.get("paper_trading_status") or "") != "passed"
    )
    if blocked_confidence_count:
        _add_prompt_mutation_candidate(
            candidates,
            run_id=run_id,
            candidate_type="confidence_gate_rule",
            target_scope="report_intelligence.confidence_impact",
            target_component="confidence_impact_gate",
            proposed_change=(
                "Keep confidence_delta at zero for every recipe without passed "
                "paper-trading validation and lockbox approval."
            ),
            trigger_sources=[
                "confidence_impact_observations",
                "recipe_paper_trading_summary",
            ],
            evidence_refs=[
                {
                    "artifact_path": "registry/report_intelligence/confidence_impact_observations.jsonl",
                    "field": "paper_trading_status",
                    "blocked_observation_count": blocked_confidence_count,
                }
            ],
            severity="high",
            blocked_by=["paper_trading_validation_required", "lockbox_required"],
        )
    markdown_summary = _ensure_mapping(markdown_coverage_summary)
    coverage_gate_blockers = [
        str(item)
        for item in _ensure_list(markdown_summary.get("coverage_gate_blockers"))
        if str(item).strip()
    ]
    if (
        str(markdown_summary.get("coverage_gate_status") or "") == "blocked"
        or coverage_gate_blockers
    ):
        _add_prompt_mutation_candidate(
            candidates,
            run_id=run_id,
            candidate_type="markdown_coverage_expansion_rule",
            target_scope="report_intelligence.markdown_corpus_expansion",
            target_component="report_selection_and_mineru_pipeline",
            proposed_change=(
                "Expand private PDF-to-Markdown coverage to the P9 thresholds "
                "before allowing prompt evolution to depend on report-derived "
                "Markdown evidence."
            ),
            trigger_sources=["markdown_coverage_summary"],
            evidence_refs=[
                {
                    "artifact_path": "registry/report_intelligence/markdown_coverage_summary.json",
                    "field": "coverage_gate_status",
                    "coverage_gate_status": str(
                        markdown_summary.get("coverage_gate_status") or ""
                    ),
                    "coverage_gate_blockers": coverage_gate_blockers,
                    "coverage_targets": _ensure_mapping(
                        markdown_summary.get("coverage_targets")
                    ),
                    "selected_report_count": int(
                        markdown_summary.get("selected_report_count") or 0
                    ),
                    "markdown_ready_count": int(
                        markdown_summary.get("markdown_ready_count") or 0
                    ),
                    "markdown_quality_pass_count": int(
                        markdown_summary.get("markdown_quality_pass_count") or 0
                    ),
                    "llm_extraction_processed_count": int(
                        markdown_summary.get("llm_extraction_processed_count") or 0
                    ),
                }
            ],
            severity="high",
            blocked_by=[
                "p9_markdown_coverage_target_pending",
                "manual_corpus_quality_review_required",
            ],
        )
    quality_gaps = _count_mapping_values(
        _ensure_mapping(markdown_summary.get("markdown_quality_gap_counts"))
    )
    retry_queue_count = int(markdown_summary.get("retry_queue_count") or 0)
    if quality_gaps or retry_queue_count:
        _add_prompt_mutation_candidate(
            candidates,
            run_id=run_id,
            candidate_type="markdown_quality_rule",
            target_scope="report_intelligence.markdown_extraction",
            target_component="mineru_quality_gate",
            proposed_change=(
                "Route low-quality Markdown conversions to retry or manual review "
                "before LLM extraction, preserving private PDF and Markdown caches."
            ),
            trigger_sources=["markdown_coverage_summary"],
            evidence_refs=[
                {
                    "artifact_path": "registry/report_intelligence/markdown_coverage_summary.json",
                    "field": "markdown_quality_gap_counts",
                    "gap_counts": quality_gaps,
                    "retry_queue_count": retry_queue_count,
                }
            ],
            severity="medium",
            blocked_by=["markdown_quality_review_required"],
        )
    return sorted(candidates, key=lambda row: str(row.get("mutation_candidate_id") or ""))


def write_report_intelligence_prompt_mutation_candidates(
    registry_dir: str | Path,
    *,
    run_id: str = "RIR-PROMPT-MUTATION-CANDIDATES",
) -> dict[str, Any]:
    registry_path = Path(registry_dir)
    blockers: list[str] = []
    outcome_labeling_readiness = _read_registry_json(
        registry_path / "outcome_labeling_readiness.json",
        label="outcome_labeling_readiness",
        blockers=blockers,
    )
    tool_gap_rows = _read_registry_jsonl(
        registry_path / "tool_gaps.jsonl",
        label="tool_gaps",
        blockers=blockers,
    )
    recipe_paper_trading_run_rows = _read_registry_jsonl(
        registry_path / "recipe_paper_trading_runs.jsonl",
        label="recipe_paper_trading_runs",
        blockers=blockers,
    )
    confidence_impact_observation_rows = _read_registry_jsonl(
        registry_path / "confidence_impact_observations.jsonl",
        label="confidence_impact_observations",
        blockers=blockers,
    )
    confidence_impact_monitor = _read_registry_json(
        registry_path / "confidence_impact_monitor.json",
        label="confidence_impact_monitor",
        blockers=blockers,
    )
    markdown_coverage_summary = _read_registry_json(
        registry_path / "markdown_coverage_summary.json",
        label="markdown_coverage_summary",
        blockers=blockers,
    )
    industry_etf_proxy_pit_availability = _read_registry_json(
        registry_path / "industry_etf_proxy_pit_availability.json",
        label="industry_etf_proxy_pit_availability",
        blockers=blockers,
    )
    forecast_rows = _read_registry_jsonl(
        registry_path / "report_forecast_ledger.jsonl",
        label="report_forecast_ledger",
        blockers=blockers,
    )
    outcome_label_path = registry_path / "report_outcome_labels.jsonl"
    outcome_label_rows = (
        _read_registry_jsonl(
            outcome_label_path,
            label="report_outcome_labels",
            blockers=blockers,
        )
        if outcome_label_path.exists()
        else []
    )
    evolution_readiness_gate = _read_registry_json(
        registry_path / "evolution_readiness_gate.json",
        label="evolution_readiness_gate",
        blockers=blockers,
    )
    rows = build_prompt_mutation_candidates(
        run_id=run_id,
        outcome_labeling_readiness=outcome_labeling_readiness,
        tool_gap_rows=tool_gap_rows,
        recipe_paper_trading_runs=recipe_paper_trading_run_rows,
        confidence_impact_observation_rows=confidence_impact_observation_rows,
        confidence_impact_monitor=confidence_impact_monitor,
        markdown_coverage_summary=markdown_coverage_summary,
        industry_etf_proxy_pit_availability=industry_etf_proxy_pit_availability,
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_label_rows,
        evolution_readiness_gate=evolution_readiness_gate,
    )
    if blockers and not rows:
        _add_prompt_mutation_candidate(
            rows,
            run_id=run_id,
            candidate_type="evolution_input_load_gap",
            target_scope="report_intelligence.prompt_evolution",
            target_component="prompt_mutation_candidate_builder",
            proposed_change=(
                "Hold prompt evolution until required public derived evidence "
                "artifacts can be loaded without parse or presence blockers."
            ),
            trigger_sources=["artifact_load_blockers"],
            evidence_refs=[
                {
                    "artifact_path": "registry/report_intelligence",
                    "field": "load_blockers",
                    "blocker_count": len(blockers),
                }
            ],
            severity="high",
            blocked_by=["artifact_load_blockers"],
        )
    return {
        "prompt_mutation_candidates": str(
            _write_jsonl(
                registry_path / "prompt_mutation_candidates.jsonl",
                rows,
            )["path"]
        )
    }


def _bounded_prior_weight(value: float) -> float:
    return round(min(1.2, max(0.8, value)), 6)


def _source_profile_id_candidates(
    claim: Mapping[str, Any],
    metadata_by_source: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    row = metadata_by_source.get(str(claim.get("source_id") or "")) or {}
    candidates: list[str] = []
    for entity_type, entity_id in [
        ("institution", row.get("institution_id")),
        *[
            ("author", author_id)
            for author_id in _ensure_list(row.get("author_ids"))
        ],
    ]:
        if not str(entity_id or "").strip():
            continue
        candidates.append(
            _stable_id(
                "SPP",
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "sector": row.get("sector") or "unknown",
                },
            )
        )
    return candidates


def _profile_multiplier(
    profile: Mapping[str, Any] | None,
    field: str,
) -> float:
    if not profile:
        return 1.0
    try:
        return float(profile.get(field) or 1.0)
    except (TypeError, ValueError):
        return 1.0


def _claim_source_weight_multiplier(
    claim: Mapping[str, Any],
    *,
    metadata_by_source: Mapping[str, Mapping[str, Any]],
    source_profiles_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[float, bool]:
    values: list[float] = []
    matched_valid_profile = False
    for profile_id in _source_profile_id_candidates(claim, metadata_by_source):
        profile = source_profiles_by_id.get(profile_id)
        if not profile:
            continue
        values.append(_profile_multiplier(profile, "weight_multiplier"))
        if profile.get("insufficient_data") is False:
            matched_valid_profile = True
    if not values:
        return 1.0, False
    return _bounded_prior_weight(sum(values) / len(values)), matched_valid_profile


def _claim_viewpoint_weight_multiplier(
    claim: Mapping[str, Any],
    *,
    viewpoint_profiles_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[float, bool]:
    cluster_id, _ = _viewpoint_cluster_id(claim)
    profile_id = _stable_id("VPP", {"viewpoint_cluster_id": cluster_id})
    profile = viewpoint_profiles_by_id.get(profile_id)
    if not profile:
        return 1.0, False
    return (
        _bounded_prior_weight(
            _profile_multiplier(profile, "viewpoint_weight_multiplier")
        ),
        profile.get("insufficient_data") is False,
    )


def build_weighted_research_contexts(
    *,
    forecast_rows: Sequence[Mapping[str, Any]],
    footprint_rows: Sequence[Mapping[str, Any]],
    analysis_recipe_rows: Sequence[Mapping[str, Any]],
    tool_gap_rows: Sequence[Mapping[str, Any]],
    forecast_ledger_rows: Sequence[Mapping[str, Any]] = (),
    metadata_rows: Sequence[Mapping[str, Any]] = (),
    source_performance_profile_rows: Sequence[Mapping[str, Any]] = (),
    viewpoint_performance_profile_rows: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    agents = {
        str(agent)
        for footprint in footprint_rows
        for agent in _ensure_list(footprint.get("target_agent_candidates"))
        if str(agent).strip()
    } or {"research.general"}
    metadata_by_source = _source_report_metadata(metadata_rows)
    source_profiles_by_id = {
        str(profile.get("profile_id") or ""): profile
        for profile in source_performance_profile_rows
    }
    viewpoint_profiles_by_id = {
        str(profile.get("viewpoint_profile_id") or ""): profile
        for profile in viewpoint_performance_profile_rows
    }
    ledger_by_claim_id = {
        str(row.get("forecast_claim_id") or ""): row
        for row in forecast_ledger_rows
        if str(row.get("forecast_claim_id") or "").strip()
    }
    retrieved_claims = []
    for claim in forecast_rows:
        claim_id = str(claim.get("forecast_claim_id") or "")
        ledger = ledger_by_claim_id.get(claim_id) or {}
        source_weight, source_match = _claim_source_weight_multiplier(
            claim,
            metadata_by_source=metadata_by_source,
            source_profiles_by_id=source_profiles_by_id,
        )
        viewpoint_weight, viewpoint_match = _claim_viewpoint_weight_multiplier(
            claim,
            viewpoint_profiles_by_id=viewpoint_profiles_by_id,
        )
        combined_weight = _bounded_prior_weight(source_weight * viewpoint_weight)
        if source_match and viewpoint_match:
            performance_context_match = "source_and_viewpoint_profile_match"
        elif source_match:
            performance_context_match = "source_profile_match"
        elif viewpoint_match:
            performance_context_match = "viewpoint_profile_match"
        else:
            performance_context_match = "insufficient_data"
        retrieved_claims.append(
            {
                "claim_id": claim.get("claim_id"),
                "forecast_claim_id": claim.get("forecast_claim_id"),
                "forecast_family_id": ledger.get("forecast_family_id") or "",
                "dedup_cluster_id": ledger.get("dedup_cluster_id") or "",
                "consensus_cluster_id": ledger.get("consensus_cluster_id") or "",
                "copying_risk_bucket": ledger.get("copying_risk_bucket") or "unknown",
                "source_dependency_score": ledger.get("source_dependency_score"),
                "independent_viewpoint_count": ledger.get("independent_viewpoint_count"),
                "independent_confirmation_policy": (
                    "consensus_cluster_not_independent_confirmation"
                ),
                "source_span_ids": _ensure_list(claim.get("source_span_ids")),
                "source_weight_multiplier": source_weight,
                "viewpoint_weight_multiplier": viewpoint_weight,
                "combined_research_prior_weight": combined_weight,
                "performance_context_match": performance_context_match,
                "testability": claim.get("forecast_testability") or "unknown",
                "current_data_required": True,
                "current_tool_evidence_ids": [],
            }
        )
    contexts: list[dict[str, Any]] = []
    for agent_id in sorted(agents):
        contexts.append(
            {
                "weighted_context_id": _stable_id("WRC", {"agent_id": agent_id}),
                "agent_id": agent_id,
                "as_of_datetime": _utc_now(),
                "retrieved_claims": retrieved_claims,
                "retrieved_footprints": [
                    {
                        "footprint_id": footprint.get("footprint_id"),
                        "metric_candidate_ids": [
                            _stable_id(
                                "METRIC",
                                {
                                    "canonical_name": _canonical_metric_name(
                                        str(
                                            _ensure_mapping(mention).get("canonical_metric_candidate")
                                            or _ensure_mapping(mention).get("indicator_text")
                                            or ""
                                        )
                                    )
                                },
                            )
                            for mention in _ensure_list(footprint.get("indicator_mentions"))
                        ],
                        "method_pattern_ids": [],
                        "runtime_role": "tool_hint_only",
                        "current_tool_coverage": "unknown",
                    }
                    for footprint in footprint_rows
                    if agent_id in _ensure_list(footprint.get("target_agent_candidates"))
                    or agent_id == "research.general"
                ],
                "available_analysis_recipes": [
                    {
                        "analysis_recipe_id": recipe.get("analysis_recipe_id"),
                        "runtime_mode": recipe.get("runtime_mode"),
                        "validation_status": recipe.get("validation_status"),
                    }
                    for recipe in analysis_recipe_rows
                ],
                "tool_gaps": [
                    {
                        "tool_gap_id": gap.get("tool_gap_id"),
                        "missing_metric": gap.get("metric_name"),
                        "impact": "cannot fully confirm report-derived method until tool coverage is resolved",
                    }
                    for gap in tool_gap_rows
                ],
                "research_only": True,
                "actionability": REPORT_INTELLIGENCE_SAFE_ACTIONABILITY,
            }
        )
    return contexts


def build_runtime_tool_gap_observations(
    *,
    run_id: str,
    weighted_research_context_rows: Sequence[Mapping[str, Any]],
    tool_gap_rows: Sequence[Mapping[str, Any]],
    analysis_recipe_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    recipes_by_method_id: dict[str, list[str]] = {}
    for recipe in analysis_recipe_rows:
        method_pattern_id = str(recipe.get("method_pattern_id") or "")
        recipe_id = str(recipe.get("analysis_recipe_id") or "")
        if method_pattern_id and recipe_id:
            recipes_by_method_id.setdefault(method_pattern_id, []).append(recipe_id)

    context_agent_ids = [
        str(context.get("agent_id") or "")
        for context in weighted_research_context_rows
        if str(context.get("agent_id") or "").strip()
    ]
    observations: list[dict[str, Any]] = []
    for gap in tool_gap_rows:
        gap_id = str(gap.get("tool_gap_id") or "")
        if not gap_id:
            continue
        target_agents = [
            str(agent)
            for agent in _ensure_list(gap.get("target_agents"))
            if str(agent).strip()
        ] or context_agent_ids or ["research.general"]
        method_pattern_ids = [
            str(method_id)
            for method_id in _ensure_list(gap.get("method_pattern_ids"))
            if str(method_id).strip()
        ]
        blocked_recipe_ids = sorted(
            {
                recipe_id
                for method_id in method_pattern_ids
                for recipe_id in recipes_by_method_id.get(method_id, ())
            }
        )
        metric_candidate_id = str(gap.get("metric_candidate_id") or "")
        metric_name = str(gap.get("metric_name") or "")
        for agent_id in sorted(dict.fromkeys(target_agents)):
            observations.append(
                {
                    "runtime_gap_id": _stable_id(
                        "RTG",
                        {
                            "agent_id": agent_id,
                            "tool_gap_id": gap_id,
                            "metric_candidate_id": metric_candidate_id,
                        },
                    ),
                    "agent_id": agent_id,
                    "run_id": run_id,
                    "missing_metric_candidate_id": metric_candidate_id,
                    "missing_metric": metric_name,
                    "blocked_rule_ids": [],
                    "blocked_recipe_ids": blocked_recipe_ids,
                    "impact_on_output": (
                        "confidence_cap_reduced_to_0.60; "
                        "no_trade_without_current_data_confirmation"
                    ),
                    "fallback_used": True,
                    "suggested_tool_gap_id": gap_id,
                    "runtime_role": "gap_observation_only",
                    "research_only": True,
                    "actionability": REPORT_INTELLIGENCE_SAFE_ACTIONABILITY,
                    "allowed_runtime_mode": "shadow_only",
                    "current_data_confirmation": "missing",
                }
            )
    return observations


def _audit_check(
    *,
    check_id: str,
    requirement: str,
    evidence: Mapping[str, Any],
    failures: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "requirement": requirement,
        "accepted": not failures,
        "failure_count": len(failures),
        "failures": list(failures),
        "evidence": dict(evidence),
    }


def _iter_context_retrieved_claims(
    context_rows: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    return [
        claim
        for context in context_rows
        for claim in _ensure_list(context.get("retrieved_claims"))
        if isinstance(claim, Mapping)
    ]


def _iter_context_retrieved_footprints(
    context_rows: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    return [
        footprint
        for context in context_rows
        for footprint in _ensure_list(context.get("retrieved_footprints"))
        if isinstance(footprint, Mapping)
    ]


def _contains_forbidden_shadow_output_field(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in REPORT_INTELLIGENCE_FORBIDDEN_SHADOW_OUTPUT_FIELDS:
                return str(key)
            nested = _contains_forbidden_shadow_output_field(item)
            if nested:
                return nested
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            nested = _contains_forbidden_shadow_output_field(item)
            if nested:
                return nested
    return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_report_intelligence_runtime_safety_audit(
    *,
    run_id: str,
    feature_flags: Mapping[str, Any],
    forecast_rows: Sequence[Mapping[str, Any]],
    forecast_ledger_rows: Sequence[Mapping[str, Any]],
    method_rows: Sequence[Mapping[str, Any]],
    analysis_recipe_rows: Sequence[Mapping[str, Any]],
    weighted_research_context_rows: Sequence[Mapping[str, Any]],
    runtime_tool_gap_observation_rows: Sequence[Mapping[str, Any]],
    tool_gap_rows: Sequence[Mapping[str, Any]],
    load_blockers: Sequence[str] = (),
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    loaded_failures = list(load_blockers)
    checks.append(
        _audit_check(
            check_id="RI-SAFE-00",
            requirement="Required report-intelligence safety inputs load successfully.",
            evidence={"load_blocker_count": len(loaded_failures)},
            failures=loaded_failures,
        )
    )

    flags = _ensure_mapping(feature_flags.get("flags"))
    rollout_mode = str(feature_flags.get("rollout_mode") or "")
    rollout_index = REPORT_INTELLIGENCE_ROLLOUT_MODES.index(rollout_mode) if rollout_mode in REPORT_INTELLIGENCE_ROLLOUT_MODES else -1
    max_safe_index = REPORT_INTELLIGENCE_ROLLOUT_MODES.index(
        REPORT_INTELLIGENCE_MAX_SAFE_ROLLOUT_MODE
    )
    flag_failures: list[str] = []
    if rollout_index < 0:
        flag_failures.append("feature_flags.rollout_mode must be a known rollout mode")
    elif rollout_index > max_safe_index:
        flag_failures.append(
            f"rollout_mode {rollout_mode} exceeds {REPORT_INTELLIGENCE_MAX_SAFE_ROLLOUT_MODE}"
        )
    if flags.get("production_use_of_weighted_reports") is True:
        flag_failures.append("production_use_of_weighted_reports must remain false")
    checks.append(
        _audit_check(
            check_id="RI-SAFE-01",
            requirement="Report intelligence rollout remains at or below shadow tooling.",
            evidence={
                "rollout_mode": rollout_mode,
                "production_use_of_weighted_reports": flags.get(
                    "production_use_of_weighted_reports"
                ),
            },
            failures=flag_failures,
        )
    )

    actionability_failures: list[str] = []
    for index, row in enumerate(weighted_research_context_rows, 1):
        if row.get("research_only") is not True:
            actionability_failures.append(
                f"weighted_research_contexts row {index}: research_only must be true"
            )
        if row.get("actionability") != REPORT_INTELLIGENCE_SAFE_ACTIONABILITY:
            actionability_failures.append(
                f"weighted_research_contexts row {index}: actionability must block trading without current data"
            )
    for index, row in enumerate(runtime_tool_gap_observation_rows, 1):
        if row.get("research_only") is not True:
            actionability_failures.append(
                f"runtime_tool_gap_observations row {index}: research_only must be true"
            )
        if row.get("actionability") != REPORT_INTELLIGENCE_SAFE_ACTIONABILITY:
            actionability_failures.append(
                f"runtime_tool_gap_observations row {index}: actionability must block trading without current data"
            )
        if row.get("current_data_confirmation") != "missing":
            actionability_failures.append(
                f"runtime_tool_gap_observations row {index}: current data confirmation must remain missing"
            )
    checks.append(
        _audit_check(
            check_id="RI-SAFE-02",
            requirement="Research-only support cannot produce actionable recommendations.",
            evidence={
                "weighted_context_rows": len(weighted_research_context_rows),
                "runtime_gap_observation_rows": len(runtime_tool_gap_observation_rows),
                "safe_actionability": REPORT_INTELLIGENCE_SAFE_ACTIONABILITY,
            },
            failures=actionability_failures,
        )
    )

    forbidden_failures: list[str] = []
    for label, rows in (
        ("weighted_research_contexts", weighted_research_context_rows),
        ("runtime_tool_gap_observations", runtime_tool_gap_observation_rows),
    ):
        for index, row in enumerate(rows, 1):
            forbidden_key = _contains_forbidden_shadow_output_field(row)
            if forbidden_key:
                forbidden_failures.append(
                    f"{label} row {index}: forbidden decision-impact field {forbidden_key}"
                )
    checks.append(
        _audit_check(
            check_id="RI-SAFE-03",
            requirement="Shadow report-intelligence outputs do not change sector score, sizing, or orders.",
            evidence={
                "forbidden_fields": list(
                    REPORT_INTELLIGENCE_FORBIDDEN_SHADOW_OUTPUT_FIELDS
                ),
                "checked_rows": len(weighted_research_context_rows)
                + len(runtime_tool_gap_observation_rows),
            },
            failures=forbidden_failures,
        )
    )

    footprint_failures: list[str] = []
    retrieved_footprints = _iter_context_retrieved_footprints(
        weighted_research_context_rows
    )
    for index, footprint in enumerate(retrieved_footprints, 1):
        if footprint.get("runtime_role") != "tool_hint_only":
            footprint_failures.append(
                f"retrieved_footprints row {index}: runtime_role must be tool_hint_only"
            )
        if footprint.get("evidence_type") == "current_tool_data":
            footprint_failures.append(
                f"retrieved_footprints row {index}: analytical footprint cannot be current_tool_data evidence"
            )
        if "confidence_impact" in footprint:
            footprint_failures.append(
                f"retrieved_footprints row {index}: confidence_impact is forbidden"
            )
    checks.append(
        _audit_check(
            check_id="RI-SAFE-04",
            requirement="Analytical footprints remain metadata/tool hints, not current data evidence.",
            evidence={"retrieved_footprint_rows": len(retrieved_footprints)},
            failures=footprint_failures,
        )
    )

    retrieved_claims = _iter_context_retrieved_claims(weighted_research_context_rows)
    forecast_ids = {
        str(row.get("forecast_claim_id") or "")
        for row in forecast_rows
        if str(row.get("forecast_claim_id") or "").strip()
    }
    retrieved_ids = {
        str(row.get("forecast_claim_id") or "")
        for row in retrieved_claims
        if str(row.get("forecast_claim_id") or "").strip()
    }
    missing_retrieved_ids = sorted(forecast_ids - retrieved_ids)
    low_weight_retained_ids = sorted(
        {
            str(row.get("forecast_claim_id") or "")
            for row in retrieved_claims
            if (_float_or_none(row.get("combined_research_prior_weight")) or 1.0)
            < 1.0
            and str(row.get("forecast_claim_id") or "").strip()
        }
    )
    checks.append(
        _audit_check(
            check_id="RI-SAFE-05",
            requirement="Low-weight or disagreeing research is downweighted but not erased.",
            evidence={
                "forecast_claim_count": len(forecast_ids),
                "unique_retrieved_claim_count": len(retrieved_ids),
                "low_weight_retained_count": len(low_weight_retained_ids),
                "sample_low_weight_retained_ids": low_weight_retained_ids[:10],
            },
            failures=[
                f"forecast claim not retained in weighted context: {claim_id}"
                for claim_id in missing_retrieved_ids[:20]
            ],
        )
    )

    inversion_failures: list[str] = []
    for index, claim in enumerate(retrieved_claims, 1):
        weight = _float_or_none(claim.get("combined_research_prior_weight"))
        if weight is None:
            inversion_failures.append(
                f"retrieved_claims row {index}: combined_research_prior_weight must be numeric"
            )
        elif weight < 0.0 or weight > 1.2:
            inversion_failures.append(
                f"retrieved_claims row {index}: combined weight must stay positive and bounded"
            )
        if claim.get("current_data_required") is not True:
            inversion_failures.append(
                f"retrieved_claims row {index}: current_data_required must be true"
            )
        if claim.get("auto_inverted") is True or claim.get("contrarian_signal") is True:
            inversion_failures.append(
                f"retrieved_claims row {index}: bad sources must not become automatic contrarian signals"
            )
    checks.append(
        _audit_check(
            check_id="RI-SAFE-06",
            requirement="Historically weak sources are not automatically inverted into contrarian signals.",
            evidence={
                "retrieved_claim_rows": len(retrieved_claims),
                "max_allowed_weight": 1.2,
                "min_allowed_weight": 0.0,
            },
            failures=inversion_failures,
        )
    )

    ledger_failures: list[str] = []
    ledger_by_claim_id = {
        str(row.get("forecast_claim_id") or ""): row
        for row in forecast_ledger_rows
        if str(row.get("forecast_claim_id") or "").strip()
    }
    for index, row in enumerate(forecast_ledger_rows, 1):
        for field in (
            "forecast_family_id",
            "dedup_cluster_id",
            "consensus_cluster_id",
            "copying_risk_bucket",
            "source_dependency_score",
            "independent_viewpoint_count",
        ):
            if field not in row:
                ledger_failures.append(
                    f"report_forecast_ledger row {index}: {field} required for correlation governance"
                )
    for index, claim in enumerate(retrieved_claims, 1):
        claim_id = str(claim.get("forecast_claim_id") or "")
        if claim_id not in ledger_by_claim_id:
            continue
        if not str(claim.get("consensus_cluster_id") or "").strip():
            ledger_failures.append(
                f"retrieved_claims row {index}: consensus_cluster_id required"
            )
        if not str(claim.get("dedup_cluster_id") or "").strip():
            ledger_failures.append(
                f"retrieved_claims row {index}: dedup_cluster_id required"
            )
        if (
            claim.get("independent_confirmation_policy")
            != "consensus_cluster_not_independent_confirmation"
        ):
            ledger_failures.append(
                f"retrieved_claims row {index}: independent confirmation policy missing"
            )
    consensus_cluster_count = len(
        {
            str(row.get("consensus_cluster_id") or "")
            for row in forecast_ledger_rows
            if str(row.get("consensus_cluster_id") or "").strip()
        }
    )
    checks.append(
        _audit_check(
            check_id="RI-SAFE-07",
            requirement="Correlated or copied sources are tracked by consensus/dedup clusters, not counted as independent confirmations.",
            evidence={
                "forecast_ledger_rows": len(forecast_ledger_rows),
                "consensus_cluster_count": consensus_cluster_count,
                "retrieved_claim_rows": len(retrieved_claims),
            },
            failures=ledger_failures,
        )
    )

    gap_ids = {
        str(row.get("tool_gap_id") or "")
        for row in tool_gap_rows
        if str(row.get("tool_gap_id") or "").strip()
    }
    gap_feedback_failures: list[str] = []
    for index, row in enumerate(runtime_tool_gap_observation_rows, 1):
        gap_id = str(row.get("suggested_tool_gap_id") or "")
        if gap_id not in gap_ids:
            gap_feedback_failures.append(
                f"runtime_tool_gap_observations row {index}: suggested_tool_gap_id missing from tool_gap_registry"
            )
        if row.get("runtime_role") != "gap_observation_only":
            gap_feedback_failures.append(
                f"runtime_tool_gap_observations row {index}: runtime_role must be gap_observation_only"
            )
        if row.get("fallback_used") is not True:
            gap_feedback_failures.append(
                f"runtime_tool_gap_observations row {index}: fallback_used must be true"
            )
    checks.append(
        _audit_check(
            check_id="RI-SAFE-08",
            requirement="Runtime tool gaps feed back into the tool gap registry without affecting decisions.",
            evidence={
                "runtime_gap_observation_rows": len(runtime_tool_gap_observation_rows),
                "tool_gap_rows": len(tool_gap_rows),
            },
            failures=gap_feedback_failures,
        )
    )

    recipe_failures: list[str] = []
    for index, row in enumerate(method_rows, 1):
        if row.get("allowed_runtime_mode") != "shadow_only":
            recipe_failures.append(
                f"method_patterns row {index}: allowed_runtime_mode must be shadow_only"
            )
    for index, row in enumerate(analysis_recipe_rows, 1):
        if row.get("runtime_mode") != "shadow_only":
            recipe_failures.append(
                f"analysis_recipes row {index}: runtime_mode must be shadow_only"
            )
        if row.get("validation_status") not in {"candidate", "shadow_validated"}:
            recipe_failures.append(
                f"analysis_recipes row {index}: validation_status must remain pre-paper-trading"
            )
    checks.append(
        _audit_check(
            check_id="RI-SAFE-09",
            requirement="Method patterns and recipes cannot jump beyond shadow mode without validation gates.",
            evidence={
                "method_pattern_rows": len(method_rows),
                "analysis_recipe_rows": len(analysis_recipe_rows),
            },
            failures=recipe_failures,
        )
    )

    blockers = [
        failure
        for check in checks
        for failure in _ensure_list(check.get("failures"))
        if str(failure).strip()
    ]
    return {
        "audit_id": "RKE-REPORT-INTELLIGENCE-RUNTIME-SAFETY-AUDIT",
        "run_id": run_id,
        "as_of_datetime": _utc_now(),
        "accepted": not blockers,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "checked_item_count": sum(
            [
                len(forecast_rows),
                len(forecast_ledger_rows),
                len(method_rows),
                len(analysis_recipe_rows),
                len(weighted_research_context_rows),
                len(runtime_tool_gap_observation_rows),
                len(tool_gap_rows),
            ]
        ),
        "checks": checks,
        "policy": (
            "report intelligence may rank research priors, recipes, and tool gaps in "
            "shadow mode only; it cannot create current market evidence, actionable "
            "recommendations, sector scores, sizing, orders, or contrarian signals "
            "without current tool data, validation, paper trading, and promotion gates"
        ),
    }


def write_report_intelligence_runtime_safety_audit(
    registry_dir: str | Path,
    *,
    run_id: str = "RIR-SAFETY-AUDIT",
    feature_flags: Mapping[str, Any] | None = None,
    forecast_rows: Sequence[Mapping[str, Any]] | None = None,
    forecast_ledger_rows: Sequence[Mapping[str, Any]] | None = None,
    method_rows: Sequence[Mapping[str, Any]] | None = None,
    analysis_recipe_rows: Sequence[Mapping[str, Any]] | None = None,
    weighted_research_context_rows: Sequence[Mapping[str, Any]] | None = None,
    runtime_tool_gap_observation_rows: Sequence[Mapping[str, Any]] | None = None,
    tool_gap_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    registry_path = Path(registry_dir)
    blockers: list[str] = []
    if feature_flags is None:
        feature_flags = _read_registry_json(
            registry_path / "feature_flags.json",
            label="feature_flags",
            blockers=blockers,
        )
    if forecast_rows is None:
        forecast_rows = _read_registry_jsonl(
            registry_path / "forecast_claims.jsonl",
            label="forecast_claims",
            blockers=blockers,
        )
    if forecast_ledger_rows is None:
        forecast_ledger_rows = _read_registry_jsonl(
            registry_path / "report_forecast_ledger.jsonl",
            label="report_forecast_ledger",
            blockers=blockers,
        )
    if method_rows is None:
        method_rows = _read_registry_jsonl(
            registry_path / "method_patterns.jsonl",
            label="method_patterns",
            blockers=blockers,
        )
    if analysis_recipe_rows is None:
        analysis_recipe_rows = _read_registry_jsonl(
            registry_path / "analysis_recipes.jsonl",
            label="analysis_recipes",
            blockers=blockers,
        )
    if weighted_research_context_rows is None:
        weighted_research_context_rows = _read_registry_jsonl(
            registry_path / "weighted_research_contexts.jsonl",
            label="weighted_research_contexts",
            blockers=blockers,
        )
    if runtime_tool_gap_observation_rows is None:
        runtime_tool_gap_observation_rows = _read_registry_jsonl(
            registry_path / "runtime_tool_gap_observations.jsonl",
            label="runtime_tool_gap_observations",
            blockers=blockers,
        )
    if tool_gap_rows is None:
        tool_gap_rows = _read_registry_jsonl(
            registry_path / "tool_gaps.jsonl",
            label="tool_gaps",
            blockers=blockers,
        )

    audit = build_report_intelligence_runtime_safety_audit(
        run_id=run_id,
        feature_flags=feature_flags,
        forecast_rows=forecast_rows,
        forecast_ledger_rows=forecast_ledger_rows,
        method_rows=method_rows,
        analysis_recipe_rows=analysis_recipe_rows,
        weighted_research_context_rows=weighted_research_context_rows,
        runtime_tool_gap_observation_rows=runtime_tool_gap_observation_rows,
        tool_gap_rows=tool_gap_rows,
        load_blockers=blockers,
    )
    return _write_json(registry_path / "runtime_safety_audit.json", audit)


def _profile_outcome_max_exit_by_id(
    *,
    metadata_rows: Sequence[Mapping[str, Any]],
    forecast_rows: Sequence[Mapping[str, Any]],
    outcome_label_rows: Sequence[Mapping[str, Any]],
) -> dict[str, datetime]:
    metadata_by_source = _source_report_metadata(metadata_rows)
    labels_by_claim = _labels_by_claim(outcome_label_rows)
    result: dict[str, datetime] = {}
    for claim in forecast_rows:
        labels = labels_by_claim.get(str(claim.get("forecast_claim_id") or ""))
        if not labels:
            continue
        max_exit = _max_pit_datetime(labels, fields=("exit_datetime", "entry_datetime"))
        if max_exit is None:
            continue
        for profile_id in _source_profile_id_candidates(
            claim,
            metadata_by_source=metadata_by_source,
        ):
            existing = result.get(profile_id)
            if existing is None or max_exit > existing:
                result[profile_id] = max_exit
    return result


def build_report_intelligence_pit_leakage_audit(
    *,
    run_id: str,
    feature_flags: Mapping[str, Any],
    metadata_rows: Sequence[Mapping[str, Any]],
    forecast_rows: Sequence[Mapping[str, Any]],
    forecast_ledger_rows: Sequence[Mapping[str, Any]],
    outcome_label_rows: Sequence[Mapping[str, Any]],
    source_performance_profile_rows: Sequence[Mapping[str, Any]],
    tool_coverage_match_rows: Sequence[Mapping[str, Any]],
    analysis_recipe_rows: Sequence[Mapping[str, Any]],
    weighted_research_context_rows: Sequence[Mapping[str, Any]],
    load_blockers: Sequence[str] = (),
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    checks.append(
        _audit_check(
            check_id="RI-PIT-00",
            requirement="Required report-intelligence PIT inputs load successfully.",
            evidence={"load_blocker_count": len(load_blockers)},
            failures=load_blockers,
        )
    )

    metadata_by_source = _source_report_metadata(metadata_rows)
    claim_by_id = {
        str(row.get("forecast_claim_id") or ""): row
        for row in forecast_rows
        if str(row.get("forecast_claim_id") or "").strip()
    }
    ledger_by_claim_id = {
        str(row.get("forecast_claim_id") or ""): row
        for row in forecast_ledger_rows
        if str(row.get("forecast_claim_id") or "").strip()
    }
    flags = _ensure_mapping(feature_flags.get("flags"))
    rollout_mode = str(feature_flags.get("rollout_mode") or "")
    rollout_index = (
        REPORT_INTELLIGENCE_ROLLOUT_MODES.index(rollout_mode)
        if rollout_mode in REPORT_INTELLIGENCE_ROLLOUT_MODES
        else -1
    )
    max_safe_index = REPORT_INTELLIGENCE_ROLLOUT_MODES.index(
        REPORT_INTELLIGENCE_MAX_SAFE_ROLLOUT_MODE
    )
    promoted_runtime = (
        flags.get("production_use_of_weighted_reports") is True
        or rollout_index > max_safe_index
    )
    context_datetimes = [
        parsed
        for parsed in (
            _parse_pit_datetime(row.get("as_of_datetime"))
            for row in weighted_research_context_rows
        )
        if parsed is not None
    ]
    latest_context_datetime = max(context_datetimes) if context_datetimes else None

    report_access_failures: list[str] = []
    for index, claim in enumerate(forecast_rows, 1):
        claim_id = str(claim.get("forecast_claim_id") or f"row-{index}")
        metadata = metadata_by_source.get(str(claim.get("source_id") or ""))
        if not metadata:
            report_access_failures.append(f"{claim_id}: source metadata missing")
            continue
        accessible = _parse_pit_datetime(metadata.get("accessible_datetime"))
        signal = _parse_pit_datetime(claim.get("signal_datetime"))
        if accessible is None:
            report_access_failures.append(f"{claim_id}: accessible_datetime missing or invalid")
        if signal is None:
            report_access_failures.append(f"{claim_id}: signal_datetime missing or invalid")
        if accessible is not None and signal is not None and accessible > signal:
            report_access_failures.append(
                f"{claim_id}: report accessible_datetime is after claim signal_datetime"
            )
        ledger = ledger_by_claim_id.get(claim_id)
        if ledger is None:
            report_access_failures.append(f"{claim_id}: forecast ledger row missing")
            continue
        ledger_as_of = _parse_pit_datetime(ledger.get("as_of_datetime"))
        if ledger_as_of is None:
            report_access_failures.append(f"{claim_id}: ledger as_of_datetime missing or invalid")
        if accessible is not None and ledger_as_of is not None and accessible > ledger_as_of:
            report_access_failures.append(
                f"{claim_id}: report accessible_datetime is after ledger as_of_datetime"
            )
    checks.append(
        _audit_check(
            check_id="RI-PIT-01",
            requirement="Report accessible_datetime must be at or before claim/ledger decision datetime.",
            evidence={
                "forecast_claim_rows": len(forecast_rows),
                "metadata_rows": len(metadata_rows),
                "forecast_ledger_rows": len(forecast_ledger_rows),
            },
            failures=report_access_failures,
        )
    )

    outcome_failures: list[str] = []
    missing_vintage_count = 0
    stock_survivorship_unverified_count = 0
    for index, label in enumerate(outcome_label_rows, 1):
        label_id = str(label.get("outcome_id") or f"row-{index}")
        label_type = str(label.get("label_type") or "")
        claim = claim_by_id.get(str(label.get("forecast_claim_id") or ""))
        if claim is None:
            outcome_failures.append(f"{label_id}: forecast claim missing")
            continue
        metadata = metadata_by_source.get(str(claim.get("source_id") or "")) or {}
        accessible = _parse_pit_datetime(metadata.get("accessible_datetime"))
        signal = _parse_pit_datetime(claim.get("signal_datetime"))
        entry = _parse_pit_datetime(label.get("entry_datetime"))
        exit_dt = _parse_pit_datetime(label.get("exit_datetime"))
        if label.get("pit_valid") is not True:
            outcome_failures.append(f"{label_id}: pit_valid must be true")
        if label.get("survivorship_safe") is not True:
            if (
                label_type == "stock_price_proxy"
                and label.get("survivorship_check")
                == STOCK_PRICE_PROXY_SURVIVORSHIP_CHECK
            ):
                stock_survivorship_unverified_count += 1
                if promoted_runtime:
                    outcome_failures.append(
                        f"{label_id}: stock survivorship_unverified cannot support "
                        "paper trading or production rollout"
                    )
            else:
                outcome_failures.append(f"{label_id}: survivorship_safe must be true")
        if entry is None:
            outcome_failures.append(f"{label_id}: entry_datetime missing or invalid")
        if exit_dt is None:
            outcome_failures.append(f"{label_id}: exit_datetime missing or invalid")
        if entry is not None and exit_dt is not None and exit_dt < entry:
            outcome_failures.append(f"{label_id}: exit_datetime precedes entry_datetime")
        if accessible is not None and entry is not None and accessible > entry:
            outcome_failures.append(
                f"{label_id}: report accessible_datetime is after outcome entry_datetime"
            )
        if signal is not None and entry is not None and signal > entry:
            outcome_failures.append(
                f"{label_id}: claim signal_datetime is after outcome entry_datetime"
            )
        if label_type == "industry_etf_proxy":
            signal_date = _date_key(claim.get("signal_datetime"))
            entry_date = _date_key(label.get("entry_datetime"))
            if signal_date and entry_date and entry_date <= signal_date:
                outcome_failures.append(
                    f"{label_id}: industry ETF entry_datetime must be after signal date"
                )
            entry_lag = _int_or_none(label.get("entry_lag_trading_days"))
            if entry_lag is None or entry_lag < INDUSTRY_ETF_ENTRY_LAG_TRADING_DAYS:
                outcome_failures.append(
                    f"{label_id}: industry ETF entry_lag_trading_days must be >= "
                    f"{INDUSTRY_ETF_ENTRY_LAG_TRADING_DAYS}"
                )
        if label_type == "stock_price_proxy":
            signal_date = _date_key(claim.get("signal_datetime"))
            entry_date = _date_key(label.get("entry_datetime"))
            exit_date = _date_key(label.get("exit_datetime"))
            latest_calendar_date = _date_key(label.get("latest_calendar_date"))
            if signal_date and entry_date and entry_date <= signal_date:
                outcome_failures.append(
                    f"{label_id}: stock entry_datetime must be after signal date"
                )
            entry_lag = _int_or_none(label.get("entry_lag_trading_days"))
            if entry_lag is None or entry_lag < STOCK_PRICE_PROXY_ENTRY_LAG_TRADING_DAYS:
                outcome_failures.append(
                    f"{label_id}: stock entry_lag_trading_days must be >= "
                    f"{STOCK_PRICE_PROXY_ENTRY_LAG_TRADING_DAYS}"
                )
            if (
                str(label.get("benchmark_source") or "")
                == STOCK_PRICE_PROXY_BENCHMARK_SOURCE
                and label.get("benchmark_alignment") != "date_key_cross_qlib_dir"
            ):
                outcome_failures.append(
                    f"{label_id}: stock benchmark must align by date across qlib dirs"
                )
            if latest_calendar_date and exit_date and exit_date > latest_calendar_date:
                outcome_failures.append(
                    f"{label_id}: stock exit_datetime exceeds latest qlib stock calendar"
                )
            forbidden_stock_gaps = {
                "stock_entry_suspended",
                "entry_limit_locked",
                "exit_limit_locked",
                "stock_delisted_before_exit",
            }
            label_gaps = set(str(item) for item in _ensure_list(label.get("readiness_gaps")))
            leaked_gaps = sorted(forbidden_stock_gaps & label_gaps)
            if leaked_gaps:
                outcome_failures.append(
                    f"{label_id}: blocked stock readiness gaps cannot generate labels: {leaked_gaps}"
                )
        vintage_text = (
            label.get("data_vintage_datetime")
            or label.get("data_as_of_datetime")
            or label.get("data_vintage")
        )
        if vintage_text:
            vintage = _parse_pit_datetime(vintage_text)
            if vintage is None:
                outcome_failures.append(f"{label_id}: data vintage timestamp invalid")
            elif exit_dt is not None and vintage > exit_dt:
                outcome_failures.append(
                    f"{label_id}: data vintage is after outcome exit_datetime"
                )
        else:
            missing_vintage_count += 1
    checks.append(
        _audit_check(
            check_id="RI-PIT-02",
            requirement="Outcome labels must start after report access/signal and stay PIT/survivorship safe.",
            evidence={
                "outcome_label_rows": len(outcome_label_rows),
                "missing_data_vintage_count": missing_vintage_count,
                "stock_survivorship_unverified_count": (
                    stock_survivorship_unverified_count
                ),
                "stock_survivorship_policy": (
                    "allowed only for shadow stock proxy labels; promoted runtime "
                    "requires a delisted-inclusive survivorship audit"
                ),
                "missing_data_vintage_policy": (
                    "allowed in shadow labels only; labels cannot become current "
                    "tool evidence or production inputs without vintage fields"
                ),
            },
            failures=outcome_failures,
        )
    )

    profile_outcome_exit = _profile_outcome_max_exit_by_id(
        metadata_rows=metadata_rows,
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_label_rows,
    )
    profile_failures: list[str] = []
    nonzero_profile_count = 0
    for index, profile in enumerate(source_performance_profile_rows, 1):
        profile_id = str(profile.get("profile_id") or f"row-{index}")
        profile_as_of = _parse_pit_datetime(profile.get("as_of_datetime"))
        if profile_as_of is None:
            profile_failures.append(f"{profile_id}: as_of_datetime missing or invalid")
            continue
        try:
            n_nominal = int(profile.get("n_nominal") or 0)
        except (TypeError, ValueError):
            n_nominal = 0
        if n_nominal > 0:
            nonzero_profile_count += 1
            max_exit = profile_outcome_exit.get(profile_id)
            if max_exit is None:
                profile_failures.append(
                    f"{profile_id}: nonzero source profile missing PIT outcome exit evidence"
                )
            elif profile_as_of < max_exit:
                profile_failures.append(
                    f"{profile_id}: source profile as_of_datetime precedes outcome exit"
                )
            if "performance_as_of_after_outcome_exit" not in _ensure_list(
                profile.get("methodology_notes")
            ):
                profile_failures.append(
                    f"{profile_id}: methodology_notes must record outcome-exit as-of policy"
                )
        if latest_context_datetime is not None and profile_as_of > latest_context_datetime:
            profile_failures.append(
                f"{profile_id}: source profile as_of_datetime is after weighted context as_of_datetime"
            )
    checks.append(
        _audit_check(
            check_id="RI-PIT-03",
            requirement="Source performance profiles can only use outcomes observed before the profile/context as-of time.",
            evidence={
                "source_profile_rows": len(source_performance_profile_rows),
                "nonzero_source_profile_rows": nonzero_profile_count,
                "weighted_context_rows": len(weighted_research_context_rows),
            },
            failures=profile_failures,
        )
    )

    context_failures: list[str] = []
    for context_index, context in enumerate(weighted_research_context_rows, 1):
        context_as_of = _parse_pit_datetime(context.get("as_of_datetime"))
        if context_as_of is None:
            context_failures.append(
                f"weighted_research_contexts row {context_index}: as_of_datetime missing or invalid"
            )
            continue
        for claim in _ensure_list(context.get("retrieved_claims")):
            if not isinstance(claim, Mapping):
                continue
            claim_id = str(claim.get("forecast_claim_id") or "")
            source_claim = claim_by_id.get(claim_id)
            if source_claim is None:
                context_failures.append(f"{claim_id}: retrieved claim missing source forecast")
                continue
            metadata = metadata_by_source.get(str(source_claim.get("source_id") or "")) or {}
            accessible = _parse_pit_datetime(metadata.get("accessible_datetime"))
            signal = _parse_pit_datetime(source_claim.get("signal_datetime"))
            if accessible is not None and accessible > context_as_of:
                context_failures.append(
                    f"{claim_id}: retrieved report access is after context as_of_datetime"
                )
            if signal is not None and signal > context_as_of:
                context_failures.append(
                    f"{claim_id}: retrieved claim signal is after context as_of_datetime"
                )
    checks.append(
        _audit_check(
            check_id="RI-PIT-04",
            requirement="Weighted research contexts cannot retrieve future reports or future claims.",
            evidence={
                "weighted_context_rows": len(weighted_research_context_rows),
                "retrieved_claim_rows": len(
                    _iter_context_retrieved_claims(weighted_research_context_rows)
                ),
            },
            failures=context_failures,
        )
    )

    tool_failures: list[str] = []
    non_pit_covered_count = 0
    for index, coverage in enumerate(tool_coverage_match_rows, 1):
        coverage_id = str(coverage.get("coverage_id") or f"row-{index}")
        last_checked = _parse_pit_datetime(coverage.get("last_checked_at"))
        if last_checked is None:
            tool_failures.append(f"{coverage_id}: last_checked_at missing or invalid")
        elif latest_context_datetime is not None and last_checked > latest_context_datetime:
            tool_failures.append(
                f"{coverage_id}: tool coverage checked after weighted context as_of_datetime"
            )
        status = str(coverage.get("coverage_status") or "")
        pit_available = _ensure_mapping(coverage.get("coverage_details")).get(
            "pit_available"
        )
        if status in {"exact_match", "partial_match", "proxy_available"} and pit_available is not True:
            non_pit_covered_count += 1
    production_recipe_count = sum(
        1
        for row in analysis_recipe_rows
        if str(row.get("runtime_mode") or "") in {"paper_trading", "limited_production", "production"}
    )
    if non_pit_covered_count and production_recipe_count:
        tool_failures.append(
            "non-PIT tool coverage cannot support paper_trading or production recipes"
        )
    checks.append(
        _audit_check(
            check_id="RI-PIT-05",
            requirement="Tool availability checks must be PIT and non-PIT tools cannot support promoted recipes.",
            evidence={
                "tool_coverage_match_rows": len(tool_coverage_match_rows),
                "non_pit_covered_tool_count": non_pit_covered_count,
                "paper_or_production_recipe_count": production_recipe_count,
            },
            failures=tool_failures,
        )
    )

    recipe_failures: list[str] = []
    recipe_by_id = {
        str(row.get("analysis_recipe_id") or ""): row
        for row in analysis_recipe_rows
        if str(row.get("analysis_recipe_id") or "").strip()
    }
    for context_index, context in enumerate(weighted_research_context_rows, 1):
        context_as_of = _parse_pit_datetime(context.get("as_of_datetime"))
        if context_as_of is None:
            continue
        for recipe_ref in _ensure_list(context.get("available_analysis_recipes")):
            if not isinstance(recipe_ref, Mapping):
                continue
            recipe_id = str(recipe_ref.get("analysis_recipe_id") or "")
            recipe = recipe_by_id.get(recipe_id)
            if recipe is None:
                recipe_failures.append(
                    f"weighted_research_contexts row {context_index}: recipe {recipe_id} missing from registry"
                )
                continue
            if recipe_ref.get("runtime_mode") != recipe.get("runtime_mode"):
                recipe_failures.append(
                    f"weighted_research_contexts row {context_index}: recipe {recipe_id} runtime_mode mismatch"
                )
            if str(recipe.get("runtime_mode") or "") != "shadow_only":
                recipe_failures.append(
                    f"recipe {recipe_id}: runtime_mode must remain shadow_only before validation"
                )
    checks.append(
        _audit_check(
            check_id="RI-PIT-06",
            requirement="Analysis recipe runtime_mode as_of_t must be respected by weighted contexts.",
            evidence={
                "analysis_recipe_rows": len(analysis_recipe_rows),
                "weighted_context_rows": len(weighted_research_context_rows),
            },
            failures=recipe_failures,
        )
    )

    flag_failures: list[str] = []
    if flags.get("production_use_of_weighted_reports") is True:
        flag_failures.append("production_use_of_weighted_reports must remain false")
    if rollout_mode not in REPORT_INTELLIGENCE_ROLLOUT_MODES:
        flag_failures.append("rollout_mode must be recognized")
    elif (
        REPORT_INTELLIGENCE_ROLLOUT_MODES.index(rollout_mode)
        > REPORT_INTELLIGENCE_ROLLOUT_MODES.index(REPORT_INTELLIGENCE_MAX_SAFE_ROLLOUT_MODE)
    ):
        flag_failures.append(
            f"rollout_mode {rollout_mode} exceeds {REPORT_INTELLIGENCE_MAX_SAFE_ROLLOUT_MODE}"
        )
    checks.append(
        _audit_check(
            check_id="RI-PIT-07",
            requirement="PIT-limited report intelligence remains shadow-only until validation and promotion gates pass.",
            evidence={
                "rollout_mode": rollout_mode,
                "production_use_of_weighted_reports": flags.get(
                    "production_use_of_weighted_reports"
                ),
            },
            failures=flag_failures,
        )
    )

    blockers = [
        failure
        for check in checks
        for failure in _ensure_list(check.get("failures"))
        if str(failure).strip()
    ]
    return {
        "audit_id": "RKE-REPORT-INTELLIGENCE-PIT-LEAKAGE-AUDIT",
        "run_id": run_id,
        "as_of_datetime": _utc_now(),
        "accepted": not blockers,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "checked_item_count": sum(
            [
                len(metadata_rows),
                len(forecast_rows),
                len(forecast_ledger_rows),
                len(outcome_label_rows),
                len(source_performance_profile_rows),
                len(tool_coverage_match_rows),
                len(analysis_recipe_rows),
                len(weighted_research_context_rows),
            ]
        ),
        "checks": checks,
        "policy": (
            "report intelligence is point-in-time constrained: report access, "
            "forecast signals, outcome labels, source weights, tool coverage, and "
            "recipe runtime modes must all be observed no later than the context "
            "as-of time before they can influence research priors"
        ),
    }


def write_report_intelligence_pit_leakage_audit(
    registry_dir: str | Path,
    *,
    run_id: str = "RIR-PIT-LEAKAGE-AUDIT",
    feature_flags: Mapping[str, Any] | None = None,
    metadata_rows: Sequence[Mapping[str, Any]] | None = None,
    forecast_rows: Sequence[Mapping[str, Any]] | None = None,
    forecast_ledger_rows: Sequence[Mapping[str, Any]] | None = None,
    outcome_label_rows: Sequence[Mapping[str, Any]] | None = None,
    source_performance_profile_rows: Sequence[Mapping[str, Any]] | None = None,
    tool_coverage_match_rows: Sequence[Mapping[str, Any]] | None = None,
    analysis_recipe_rows: Sequence[Mapping[str, Any]] | None = None,
    weighted_research_context_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    registry_path = Path(registry_dir)
    blockers: list[str] = []
    if feature_flags is None:
        feature_flags = _read_registry_json(
            registry_path / "feature_flags.json",
            label="feature_flags",
            blockers=blockers,
        )
    if metadata_rows is None:
        metadata_rows = _read_registry_jsonl(
            registry_path / "report_metadata.jsonl",
            label="report_metadata",
            blockers=blockers,
        )
    if forecast_rows is None:
        forecast_rows = _read_registry_jsonl(
            registry_path / "forecast_claims.jsonl",
            label="forecast_claims",
            blockers=blockers,
        )
    if forecast_ledger_rows is None:
        forecast_ledger_rows = _read_registry_jsonl(
            registry_path / "report_forecast_ledger.jsonl",
            label="report_forecast_ledger",
            blockers=blockers,
        )
    if outcome_label_rows is None:
        outcome_label_rows = _read_registry_jsonl(
            registry_path / "report_outcome_labels.jsonl",
            label="report_outcome_labels",
            blockers=blockers,
        )
    if source_performance_profile_rows is None:
        source_performance_profile_rows = _read_registry_jsonl(
            registry_path / "source_performance_profiles.jsonl",
            label="source_performance_profiles",
            blockers=blockers,
        )
    if tool_coverage_match_rows is None:
        tool_coverage_match_rows = _read_registry_jsonl(
            registry_path / "tool_coverage_matches.jsonl",
            label="tool_coverage_matches",
            blockers=blockers,
        )
    if analysis_recipe_rows is None:
        analysis_recipe_rows = _read_registry_jsonl(
            registry_path / "analysis_recipes.jsonl",
            label="analysis_recipes",
            blockers=blockers,
        )
    if weighted_research_context_rows is None:
        weighted_research_context_rows = _read_registry_jsonl(
            registry_path / "weighted_research_contexts.jsonl",
            label="weighted_research_contexts",
            blockers=blockers,
        )

    audit = build_report_intelligence_pit_leakage_audit(
        run_id=run_id,
        feature_flags=feature_flags,
        metadata_rows=metadata_rows,
        forecast_rows=forecast_rows,
        forecast_ledger_rows=forecast_ledger_rows,
        outcome_label_rows=outcome_label_rows,
        source_performance_profile_rows=source_performance_profile_rows,
        tool_coverage_match_rows=tool_coverage_match_rows,
        analysis_recipe_rows=analysis_recipe_rows,
        weighted_research_context_rows=weighted_research_context_rows,
        load_blockers=blockers,
    )
    return _write_json(registry_path / "pit_leakage_audit.json", audit)


def _has_source_spans(row: Mapping[str, Any]) -> bool:
    return any(str(item).strip() for item in _ensure_list(row.get("source_span_ids")))


def _raw_data_requirements_unknown(row: Mapping[str, Any]) -> bool:
    values = [
        str(item).strip().lower()
        for item in _ensure_list(row.get("raw_data_requirements"))
        if str(item).strip()
    ]
    if not values:
        return True
    unknown_values = {"unknown", "unknown_raw_data_source", "n/a", "na", "none"}
    return all(value in unknown_values for value in values)


def build_report_intelligence_extraction_provenance_audit(
    *,
    run_id: str,
    forecast_rows: Sequence[Mapping[str, Any]],
    footprint_rows: Sequence[Mapping[str, Any]],
    metric_rows: Sequence[Mapping[str, Any]],
    forecast_ledger_rows: Sequence[Mapping[str, Any]],
    outcome_label_rows: Sequence[Mapping[str, Any]],
    outcome_labeling_readiness: Mapping[str, Any],
    load_blockers: Sequence[str] = (),
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    checks.append(
        _audit_check(
            check_id="RI-PROV-00",
            requirement="Required report-intelligence provenance inputs load successfully.",
            evidence={"load_blocker_count": len(load_blockers)},
            failures=load_blockers,
        )
    )

    claim_span_failures: list[str] = []
    source_grounded_claim_count = 0
    for index, row in enumerate(forecast_rows, 1):
        if str(row.get("claim_provenance") or "") != "source_grounded":
            continue
        source_grounded_claim_count += 1
        if not _has_source_spans(row):
            claim_span_failures.append(
                f"forecast_claims row {index}: source_grounded claim must cite source_span_ids"
            )
    checks.append(
        _audit_check(
            check_id="RI-PROV-01",
            requirement="Source-grounded forecast claims must cite source span IDs.",
            evidence={
                "forecast_claim_rows": len(forecast_rows),
                "source_grounded_claim_count": source_grounded_claim_count,
            },
            failures=claim_span_failures,
        )
    )

    footprint_span_failures: list[str] = []
    source_grounded_footprint_count = 0
    grounded_indicator_count = 0
    for index, row in enumerate(footprint_rows, 1):
        extraction_type = str(row.get("extraction_type") or "")
        has_spans = _has_source_spans(row)
        if extraction_type in {"source_grounded", "mixed"}:
            source_grounded_footprint_count += 1
            if not has_spans:
                footprint_span_failures.append(
                    f"analytical_footprints row {index}: source-grounded footprint must cite source_span_ids"
                )
        for mention_index, mention in enumerate(
            _ensure_list(row.get("indicator_mentions")),
            1,
        ):
            if not isinstance(mention, Mapping):
                footprint_span_failures.append(
                    f"analytical_footprints row {index}.indicator_mentions[{mention_index}]: expected object"
                )
                continue
            if mention.get("source_grounded") is True:
                grounded_indicator_count += 1
                if not has_spans:
                    footprint_span_failures.append(
                        f"analytical_footprints row {index}.indicator_mentions[{mention_index}]: source_grounded requires footprint spans"
                    )
    checks.append(
        _audit_check(
            check_id="RI-PROV-02",
            requirement="Source-grounded analytical footprints and indicators must cite spans, tables, or charts.",
            evidence={
                "analytical_footprint_rows": len(footprint_rows),
                "source_grounded_or_mixed_footprint_count": source_grounded_footprint_count,
                "source_grounded_indicator_count": grounded_indicator_count,
            },
            failures=footprint_span_failures,
        )
    )

    inferred_failures: list[str] = []
    accepted_claim_provenance = {
        "source_grounded",
        "analyst_or_llm_hypothesis",
        "inferred_hypothesis",
        "unknown",
    }
    accepted_failure_mode_provenance = {
        "source_grounded",
        "analyst_or_llm_hypothesis",
        "inferred_hypothesis",
    }
    accepted_footprint_types = {"source_grounded", "mixed", "inferred_hypothesis"}
    inferred_failure_mode_count = 0
    inferred_indicator_count = 0
    for index, row in enumerate(forecast_rows, 1):
        claim_provenance = str(row.get("claim_provenance") or "unknown")
        if claim_provenance not in accepted_claim_provenance:
            inferred_failures.append(
                f"forecast_claims row {index}: unsupported claim_provenance {claim_provenance}"
            )
        for mode_index, mode in enumerate(_ensure_list(row.get("failure_modes")), 1):
            if not isinstance(mode, Mapping):
                inferred_failures.append(
                    f"forecast_claims row {index}.failure_modes[{mode_index}]: expected object"
                )
                continue
            provenance = str(mode.get("provenance") or "")
            if provenance not in accepted_failure_mode_provenance:
                inferred_failures.append(
                    f"forecast_claims row {index}.failure_modes[{mode_index}]: unsupported provenance"
                )
            if provenance in {"analyst_or_llm_hypothesis", "inferred_hypothesis"}:
                inferred_failure_mode_count += 1
    for index, row in enumerate(footprint_rows, 1):
        extraction_type = str(row.get("extraction_type") or "")
        if extraction_type not in accepted_footprint_types:
            inferred_failures.append(
                f"analytical_footprints row {index}: unsupported extraction_type {extraction_type}"
            )
        for mention_index, mention in enumerate(
            _ensure_list(row.get("indicator_mentions")),
            1,
        ):
            if not isinstance(mention, Mapping):
                continue
            if not isinstance(mention.get("source_grounded"), bool):
                inferred_failures.append(
                    f"analytical_footprints row {index}.indicator_mentions[{mention_index}]: source_grounded must be boolean"
                )
            elif mention.get("source_grounded") is False:
                inferred_indicator_count += 1
    checks.append(
        _audit_check(
            check_id="RI-PROV-03",
            requirement="LLM-inferred claims, failure modes, and indicator steps must be explicitly tagged as inferred or hypothesis.",
            evidence={
                "inferred_failure_mode_count": inferred_failure_mode_count,
                "inferred_indicator_count": inferred_indicator_count,
                "accepted_inferred_tags": [
                    "analyst_or_llm_hypothesis",
                    "inferred_hypothesis",
                ],
            },
            failures=inferred_failures,
        )
    )

    scoring_failures: list[str] = []
    claim_by_id = {
        str(row.get("forecast_claim_id") or ""): row
        for row in forecast_rows
        if str(row.get("forecast_claim_id") or "").strip()
    }
    standard_outcome_claim_ids = {
        str(row.get("forecast_claim_id") or "")
        for row in outcome_label_rows
        if str(row.get("forecast_claim_id") or "").strip()
        and row.get("label_type") not in REPORT_INTELLIGENCE_PROXY_LABEL_TYPES
    }
    invalid_industry_proxy_labels: list[str] = []
    invalid_stock_proxy_labels: list[str] = []
    industry_proxy_outcome_claim_ids: set[str] = set()
    stock_proxy_outcome_claim_ids: set[str] = set()
    for index, row in enumerate(outcome_label_rows, 1):
        claim_id = str(row.get("forecast_claim_id") or "")
        if row.get("label_type") == "industry_etf_proxy":
            if claim_id:
                industry_proxy_outcome_claim_ids.add(claim_id)
            if row.get("outcome_label_source") != INDUSTRY_ETF_OUTCOME_LABEL_SOURCE:
                invalid_industry_proxy_labels.append(
                    f"report_outcome_labels row {index}: industry ETF proxy label must use {INDUSTRY_ETF_OUTCOME_LABEL_SOURCE}"
                )
            if row.get("llm_outcome_labeling_allowed") is not False:
                invalid_industry_proxy_labels.append(
                    f"report_outcome_labels row {index}: industry ETF proxy label must set llm_outcome_labeling_allowed=false"
                )
            if row.get("decision_basis") != INDUSTRY_ETF_DECISION_BASIS:
                invalid_industry_proxy_labels.append(
                    f"report_outcome_labels row {index}: industry ETF proxy label must use {INDUSTRY_ETF_DECISION_BASIS}"
                )
        if row.get("label_type") == "stock_price_proxy":
            if claim_id:
                stock_proxy_outcome_claim_ids.add(claim_id)
            if row.get("outcome_label_source") != STOCK_PRICE_PROXY_OUTCOME_LABEL_SOURCE:
                invalid_stock_proxy_labels.append(
                    f"report_outcome_labels row {index}: stock proxy label must use {STOCK_PRICE_PROXY_OUTCOME_LABEL_SOURCE}"
                )
            if row.get("llm_outcome_labeling_allowed") is not False:
                invalid_stock_proxy_labels.append(
                    f"report_outcome_labels row {index}: stock proxy label must set llm_outcome_labeling_allowed=false"
                )
            if row.get("decision_basis") != STOCK_PRICE_PROXY_DECISION_BASIS:
                invalid_stock_proxy_labels.append(
                    f"report_outcome_labels row {index}: stock proxy label must use {STOCK_PRICE_PROXY_DECISION_BASIS}"
                )
            if str(row.get("target_resolution_source") or "") not in {
                "metadata_ts_code",
                "metadata_and_llm_target_id",
                "llm_target_id",
            }:
                invalid_stock_proxy_labels.append(
                    f"report_outcome_labels row {index}: stock proxy label must record target_resolution_source"
                )
            claim = claim_by_id.get(claim_id)
            if claim is None:
                invalid_stock_proxy_labels.append(
                    f"report_outcome_labels row {index}: stock proxy forecast claim missing"
                )
            elif not _ensure_list(claim.get("source_span_ids")):
                invalid_stock_proxy_labels.append(
                    f"report_outcome_labels row {index}: stock proxy claim must have source spans"
                )
    scoring_failures.extend(invalid_industry_proxy_labels)
    scoring_failures.extend(invalid_stock_proxy_labels)
    ready_count = 0
    standard_blocked_count = 0
    unlabelable_count = 0
    for index, ledger in enumerate(forecast_ledger_rows, 1):
        claim_id = str(ledger.get("forecast_claim_id") or "")
        claim = claim_by_id.get(claim_id)
        if claim is None:
            scoring_failures.append(
                f"report_forecast_ledger row {index}: forecast_claim_id not found"
            )
            continue
        ready = (
            str(claim.get("forecast_testability") or "") == "testable"
            and not _forecast_mapping_gaps(claim)
        )
        test_status = str(ledger.get("test_status") or "")
        if ready:
            ready_count += 1
            if test_status != "ready_for_outcome_labeling":
                scoring_failures.append(
                    f"report_forecast_ledger row {index}: testable mapped forecast must be ready"
                )
        else:
            standard_blocked_count += 1
            if test_status == "ready_for_outcome_labeling":
                scoring_failures.append(
                    f"report_forecast_ledger row {index}: unmapped forecast cannot be outcome-ready"
                )
            if claim_id in standard_outcome_claim_ids:
                scoring_failures.append(
                    f"{claim_id}: unmapped or non-testable forecast entered outcome scoring"
                )
            if (
                claim_id not in industry_proxy_outcome_claim_ids
                and claim_id not in stock_proxy_outcome_claim_ids
            ):
                unlabelable_count += 1
    if outcome_labeling_readiness:
        if outcome_labeling_readiness.get("ready_for_outcome_labeling_count") != ready_count:
            scoring_failures.append("outcome_labeling_readiness ready count mismatch")
        if (
            outcome_labeling_readiness.get("standard_blocked_count")
            != standard_blocked_count
        ):
            scoring_failures.append(
                "outcome_labeling_readiness standard blocked count mismatch"
            )
        if outcome_labeling_readiness.get("blocked_count") != unlabelable_count:
            scoring_failures.append("outcome_labeling_readiness blocked count mismatch")
    checks.append(
        _audit_check(
            check_id="RI-PROV-04",
            requirement=(
                "Forecasts missing target, benchmark, direction, or horizon cannot "
                "enter standard outcome scoring; governed industry ETF proxy labels "
                "remain a separate evidence channel."
            ),
            evidence={
                "forecast_ledger_rows": len(forecast_ledger_rows),
                "ready_for_outcome_labeling_count": ready_count,
                "standard_blocked_forecast_count": standard_blocked_count,
                "unlabelable_forecast_count": unlabelable_count,
                "outcome_label_rows": len(outcome_label_rows),
                "industry_etf_proxy_outcome_claim_count": len(
                    industry_proxy_outcome_claim_ids
                ),
                "stock_price_proxy_outcome_claim_count": len(
                    stock_proxy_outcome_claim_ids
                ),
            },
            failures=scoring_failures,
        )
    )

    metric_failures: list[str] = []
    unknown_raw_source_count = 0
    promoted_unknown_count = 0
    production_metric_statuses = {
        "production",
        "production_metric",
        "production_candidate",
        "paper_trading",
        "limited_production",
    }
    for index, row in enumerate(metric_rows, 1):
        unknown_raw = _raw_data_requirements_unknown(row)
        status = str(row.get("status") or "")
        priority = str(row.get("priority_bucket") or "")
        if unknown_raw:
            unknown_raw_source_count += 1
        promoted = status in production_metric_statuses or priority in {
            "production",
            "paper_trading",
        }
        if unknown_raw and promoted:
            promoted_unknown_count += 1
            metric_failures.append(
                f"metric_candidates row {index}: unknown raw data source cannot be promoted"
            )
    checks.append(
        _audit_check(
            check_id="RI-PROV-05",
            requirement="Footprint-derived metrics with unknown raw data source cannot be promoted to production candidates.",
            evidence={
                "metric_candidate_rows": len(metric_rows),
                "unknown_raw_source_metric_count": unknown_raw_source_count,
                "promoted_unknown_raw_source_metric_count": promoted_unknown_count,
            },
            failures=metric_failures,
        )
    )

    blockers = [
        failure
        for check in checks
        for failure in _ensure_list(check.get("failures"))
        if str(failure).strip()
    ]
    return {
        "audit_id": "RKE-REPORT-INTELLIGENCE-EXTRACTION-PROVENANCE-AUDIT",
        "run_id": run_id,
        "as_of_datetime": _utc_now(),
        "accepted": not blockers,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "checked_item_count": sum(
            [
                len(forecast_rows),
                len(footprint_rows),
                len(metric_rows),
                len(forecast_ledger_rows),
                len(outcome_label_rows),
            ]
        ),
        "checks": checks,
        "policy": (
            "source-grounded forecast claims and analytical footprints must cite "
            "spans; inferred fields must stay tagged as hypotheses; unmapped "
            "forecasts and unknown-source metrics cannot be scored or promoted"
        ),
    }


def write_report_intelligence_extraction_provenance_audit(
    registry_dir: str | Path,
    *,
    run_id: str = "RIR-EXTRACTION-PROVENANCE-AUDIT",
    forecast_rows: Sequence[Mapping[str, Any]] | None = None,
    footprint_rows: Sequence[Mapping[str, Any]] | None = None,
    metric_rows: Sequence[Mapping[str, Any]] | None = None,
    forecast_ledger_rows: Sequence[Mapping[str, Any]] | None = None,
    outcome_label_rows: Sequence[Mapping[str, Any]] | None = None,
    outcome_labeling_readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    registry_path = Path(registry_dir)
    blockers: list[str] = []
    if forecast_rows is None:
        forecast_rows = _read_registry_jsonl(
            registry_path / "forecast_claims.jsonl",
            label="forecast_claims",
            blockers=blockers,
        )
    if footprint_rows is None:
        footprint_rows = _read_registry_jsonl(
            registry_path / "analytical_footprints.jsonl",
            label="analytical_footprints",
            blockers=blockers,
        )
    if metric_rows is None:
        metric_rows = _read_registry_jsonl(
            registry_path / "metric_candidates.jsonl",
            label="metric_candidates",
            blockers=blockers,
        )
    if forecast_ledger_rows is None:
        forecast_ledger_rows = _read_registry_jsonl(
            registry_path / "report_forecast_ledger.jsonl",
            label="report_forecast_ledger",
            blockers=blockers,
        )
    if outcome_label_rows is None:
        outcome_label_rows = _read_registry_jsonl(
            registry_path / "report_outcome_labels.jsonl",
            label="report_outcome_labels",
            blockers=blockers,
        )
    if outcome_labeling_readiness is None:
        outcome_labeling_readiness = _read_registry_json(
            registry_path / "outcome_labeling_readiness.json",
            label="outcome_labeling_readiness",
            blockers=blockers,
        )
    audit = build_report_intelligence_extraction_provenance_audit(
        run_id=run_id,
        forecast_rows=forecast_rows,
        footprint_rows=footprint_rows,
        metric_rows=metric_rows,
        forecast_ledger_rows=forecast_ledger_rows,
        outcome_label_rows=outcome_label_rows,
        outcome_labeling_readiness=outcome_labeling_readiness,
        load_blockers=blockers,
    )
    return _write_json(registry_path / "extraction_provenance_audit.json", audit)


def _profile_weight_field(row: Mapping[str, Any]) -> str:
    if "viewpoint_weight_multiplier" in row:
        return "viewpoint_weight_multiplier"
    return "weight_multiplier"


def _non_neutral_weight(value: Any) -> bool:
    parsed = _float_or_none(value)
    return parsed is not None and abs(parsed - 1.0) > 1e-9


def build_report_intelligence_statistical_robustness_audit(
    *,
    run_id: str,
    feature_flags: Mapping[str, Any],
    forecast_ledger_rows: Sequence[Mapping[str, Any]],
    outcome_label_rows: Sequence[Mapping[str, Any]],
    source_performance_profile_rows: Sequence[Mapping[str, Any]],
    viewpoint_performance_profile_rows: Sequence[Mapping[str, Any]],
    method_performance_profile_rows: Sequence[Mapping[str, Any]],
    weighted_research_context_rows: Sequence[Mapping[str, Any]],
    load_blockers: Sequence[str] = (),
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    checks.append(
        _audit_check(
            check_id="RI-STAT-00",
            requirement="Required report-intelligence statistical inputs load successfully.",
            evidence={"load_blocker_count": len(load_blockers)},
            failures=load_blockers,
        )
    )

    flags = _ensure_mapping(feature_flags.get("flags"))
    rollout_mode = str(feature_flags.get("rollout_mode") or "")
    rollout_index = (
        REPORT_INTELLIGENCE_ROLLOUT_MODES.index(rollout_mode)
        if rollout_mode in REPORT_INTELLIGENCE_ROLLOUT_MODES
        else -1
    )
    max_safe_index = REPORT_INTELLIGENCE_ROLLOUT_MODES.index(
        REPORT_INTELLIGENCE_MAX_SAFE_ROLLOUT_MODE
    )
    promoted_runtime = (
        flags.get("production_use_of_weighted_reports") is True
        or rollout_index > max_safe_index
    )

    label_failures: list[str] = []
    industry_proxy_label_count = 0
    stock_proxy_label_count = 0
    label_type_counts: dict[str, int] = {}
    for index, label in enumerate(outcome_label_rows, 1):
        label_id = str(label.get("outcome_id") or f"row-{index}")
        label_type = str(label.get("label_type") or "standard")
        label_type_counts[label_type] = label_type_counts.get(label_type, 0) + 1
        weight = _float_or_none(label.get("effective_n_weight"))
        if weight is None or weight <= 0.0 or weight > 1.0:
            label_failures.append(
                f"{label_id}: effective_n_weight must be in (0, 1]"
            )
        if _float_or_none(label.get("after_cost_alpha")) is None:
            label_failures.append(f"{label_id}: after_cost_alpha must be numeric")
        for required_field in ("forecast_family_id", "overlap_group_id"):
            if not str(label.get(required_field) or "").strip():
                label_failures.append(f"{label_id}: {required_field} required")

        if label.get("label_type") != "industry_etf_proxy":
            if label.get("label_type") != "stock_price_proxy":
                continue
        if label.get("label_type") == "industry_etf_proxy":
            industry_proxy_label_count += 1
            for required_field in (
                "proxy_symbol",
                "benchmark_symbol",
                "proxy_return",
                "benchmark_return",
                "relative_alpha",
                "directional_proxy_return",
                "directional_after_cost_return",
                "decision_basis",
                "outcome_label_source",
                "llm_outcome_labeling_allowed",
                "evaluation_policy",
                "window_role",
            ):
                if required_field not in label:
                    label_failures.append(
                        f"{label_id}: industry ETF proxy label missing {required_field}"
                    )
            if label.get("decision_basis") != INDUSTRY_ETF_DECISION_BASIS:
                label_failures.append(
                    f"{label_id}: decision_basis must be {INDUSTRY_ETF_DECISION_BASIS}"
                )
            if label.get("outcome_label_source") != INDUSTRY_ETF_OUTCOME_LABEL_SOURCE:
                label_failures.append(
                    f"{label_id}: outcome_label_source must be {INDUSTRY_ETF_OUTCOME_LABEL_SOURCE}"
                )
            if label.get("llm_outcome_labeling_allowed") is not False:
                label_failures.append(
                    f"{label_id}: LLM outcome labeling must be explicitly disabled"
                )
            if label.get("evaluation_policy") != INDUSTRY_ETF_EVALUATION_POLICY:
                label_failures.append(
                    f"{label_id}: evaluation_policy must retain long-horizon evidence"
                )
        if label.get("label_type") == "stock_price_proxy":
            stock_proxy_label_count += 1
            for required_field in (
                "proxy_symbol",
                "benchmark_symbol",
                "stock_return",
                "benchmark_return",
                "relative_alpha",
                "directional_stock_return",
                "directional_after_cost_return",
                "target_resolution_source",
                "benchmark_alignment",
                "decision_basis",
                "outcome_label_source",
                "llm_outcome_labeling_allowed",
                "evaluation_policy",
                "window_role",
            ):
                if required_field not in label:
                    label_failures.append(
                        f"{label_id}: stock proxy label missing {required_field}"
                    )
            if label.get("decision_basis") != STOCK_PRICE_PROXY_DECISION_BASIS:
                label_failures.append(
                    f"{label_id}: decision_basis must be {STOCK_PRICE_PROXY_DECISION_BASIS}"
                )
            if label.get("outcome_label_source") != STOCK_PRICE_PROXY_OUTCOME_LABEL_SOURCE:
                label_failures.append(
                    f"{label_id}: outcome_label_source must be {STOCK_PRICE_PROXY_OUTCOME_LABEL_SOURCE}"
                )
            if label.get("benchmark_alignment") != "date_key_cross_qlib_dir":
                label_failures.append(
                    f"{label_id}: stock benchmark must align by date across qlib dirs"
                )
            if label.get("evaluation_policy") != STOCK_PRICE_PROXY_EVALUATION_POLICY:
                label_failures.append(
                    f"{label_id}: evaluation_policy must retain long-horizon evidence"
                )
        if label.get("label_type") in REPORT_INTELLIGENCE_PROXY_LABEL_TYPES:
            if label.get("llm_outcome_labeling_allowed") is not False:
                label_failures.append(
                    f"{label_id}: LLM outcome labeling must be explicitly disabled"
                )
            if label.get("performance_value_basis") != "directional_after_cost_return":
                label_failures.append(
                    f"{label_id}: performance_value_basis must use directional after-cost return"
                )
            proxy_return = _float_or_none(
                label.get("stock_return")
                if label.get("label_type") == "stock_price_proxy"
                else label.get("proxy_return")
            )
            relative_alpha = _float_or_none(label.get("relative_alpha"))
            direction = str(label.get("direction_evaluated") or "")
            if direction == "positive" and proxy_return is not None:
                if label.get("directional_hit") is not bool(proxy_return > 0.0):
                    label_failures.append(
                        f"{label_id}: positive claim directional_hit must follow proxy return"
                    )
                if relative_alpha is not None and label.get(
                    "relative_directional_hit"
                ) is not bool(relative_alpha > 0.0):
                    label_failures.append(
                        f"{label_id}: positive claim relative_directional_hit must follow relative_alpha"
                    )
            elif direction == "negative" and proxy_return is not None:
                if label.get("directional_hit") is not bool(proxy_return < 0.0):
                    label_failures.append(
                        f"{label_id}: negative claim directional_hit must follow proxy return"
                    )
                if relative_alpha is not None and label.get(
                    "relative_directional_hit"
                ) is not bool(relative_alpha < 0.0):
                    label_failures.append(
                        f"{label_id}: negative claim relative_directional_hit must follow relative_alpha"
                    )
            else:
                label_failures.append(
                    f"{label_id}: direction_evaluated must be positive or negative"
                )
    checks.append(
        _audit_check(
            check_id="RI-STAT-01",
            requirement=(
                "Outcome labels must be rule-based after-cost observations; industry "
                "research labels are judged from mapped industry ETF returns, not LLM opinion."
            ),
            evidence={
                "outcome_label_rows": len(outcome_label_rows),
                "industry_etf_proxy_label_rows": industry_proxy_label_count,
                "stock_price_proxy_label_rows": stock_proxy_label_count,
                "label_type_counts": dict(sorted(label_type_counts.items())),
                "decision_basis": INDUSTRY_ETF_DECISION_BASIS,
                "outcome_label_source": INDUSTRY_ETF_OUTCOME_LABEL_SOURCE,
                "stock_outcome_label_source": STOCK_PRICE_PROXY_OUTCOME_LABEL_SOURCE,
                "llm_outcome_labeling_allowed": False,
            },
            failures=label_failures,
        )
    )

    profile_failures: list[str] = []
    non_neutral_profile_count = 0
    insufficient_profile_count = 0
    all_profile_rows = [
        *source_performance_profile_rows,
        *viewpoint_performance_profile_rows,
    ]
    for index, profile in enumerate(all_profile_rows, 1):
        profile_id = str(
            profile.get("profile_id")
            or profile.get("viewpoint_profile_id")
            or f"row-{index}"
        )
        n_effective = _float_or_none(profile.get("n_effective")) or 0.0
        weight_field = _profile_weight_field(profile)
        multiplier = _float_or_none(profile.get(weight_field))
        if multiplier is None:
            profile_failures.append(f"{profile_id}: {weight_field} must be numeric")
            multiplier = 1.0
        non_neutral = abs(multiplier - 1.0) > 1e-9
        if non_neutral:
            non_neutral_profile_count += 1
        if n_effective < 3.0:
            insufficient_profile_count += 1
            if profile.get("insufficient_data") is not True:
                profile_failures.append(
                    f"{profile_id}: n_effective < 3 must be marked insufficient_data"
                )
            if (
                str(profile.get("statistical_reliability_bucket") or "insufficient_data")
                != "insufficient_data"
            ):
                profile_failures.append(
                    f"{profile_id}: n_effective < 3 must keep insufficient reliability bucket"
                )
            if non_neutral:
                profile_failures.append(
                    f"{profile_id}: insufficient effective N cannot change weights"
                )
        elif non_neutral:
            notes = _ensure_list(profile.get("methodology_notes"))
            for note in (
                "effective_n_weight_overlap_adjusted",
                "neutral_prior_shrinkage_applied",
                "research_prior_only_not_signal",
            ):
                if note not in notes:
                    profile_failures.append(
                        f"{profile_id}: non-neutral profile missing methodology note {note}"
                    )
    for index, profile in enumerate(method_performance_profile_rows, 1):
        profile_id = str(profile.get("method_profile_id") or f"method-row-{index}")
        source_support = _ensure_mapping(profile.get("source_support"))
        n_effective_reports = _float_or_none(
            source_support.get("n_effective_reports")
        ) or 0.0
        if n_effective_reports < 3.0 and profile.get("insufficient_data") is not True:
            profile_failures.append(
                f"{profile_id}: method profile with n_effective_reports < 3 must remain insufficient"
            )
        if profile.get("allowed_runtime_mode") != "shadow_only":
            profile_failures.append(
                f"{profile_id}: method profile allowed_runtime_mode must be shadow_only"
            )
        if str(profile.get("validation_status") or "") not in {
            "candidate",
            "shadow_validated",
        }:
            profile_failures.append(
                f"{profile_id}: method profile validation_status must stay pre-promotion"
            )
    checks.append(
        _audit_check(
            check_id="RI-STAT-02",
            requirement=(
                "Source, viewpoint, and method weights require minimum effective N; "
                "insufficient samples stay neutral and shrink toward the parent prior."
            ),
            evidence={
                "source_profile_rows": len(source_performance_profile_rows),
                "viewpoint_profile_rows": len(viewpoint_performance_profile_rows),
                "method_profile_rows": len(method_performance_profile_rows),
                "minimum_non_neutral_effective_n": 3,
                "insufficient_profile_count": insufficient_profile_count,
                "non_neutral_profile_count": non_neutral_profile_count,
            },
            failures=profile_failures,
        )
    )

    overlap_failures: list[str] = []
    grouped_labels: dict[str, list[Mapping[str, Any]]] = {}
    for label in outcome_label_rows:
        group_id = (
            str(label.get("claim_window_set_id") or "").strip()
            or "|".join(
                [
                    str(label.get("forecast_claim_id") or ""),
                    str(label.get("label_type") or ""),
                    str(label.get("entry_datetime") or ""),
                ]
            )
        )
        grouped_labels.setdefault(group_id, []).append(label)
    complete_window_set_count = 0
    complete_stock_window_set_count = 0
    for group_id, labels in grouped_labels.items():
        total_weight = sum(_float_or_none(label.get("effective_n_weight")) or 0.0 for label in labels)
        if total_weight > 1.000001:
            overlap_failures.append(
                f"{group_id}: overlapping horizon effective_n_weight sum exceeds 1"
            )
        label_types = {str(label.get("label_type") or "") for label in labels}
        roles = {str(label.get("window_role") or "") for label in labels}
        if "industry_etf_proxy" in label_types and roles == {"short", "medium", "long"}:
            complete_window_set_count += 1
            if abs(total_weight - 1.0) > 0.000001:
                overlap_failures.append(
                    f"{group_id}: complete ETF proxy window set must sum to effective N 1"
                )
        stock_window_days = {
            int(label.get("horizon_days") or 0)
            for label in labels
            if label.get("label_type") == "stock_price_proxy"
        }
        if stock_window_days == set(STOCK_PRICE_PROXY_WINDOWS_DAYS):
            complete_stock_window_set_count += 1
            if abs(total_weight - 1.0) > 0.000001:
                overlap_failures.append(
                    f"{group_id}: complete stock proxy window set must sum to effective N 1"
                )
        for label in labels:
            role = str(label.get("window_role") or "")
            if label.get("label_type") == "industry_etf_proxy":
                if role not in INDUSTRY_ETF_PROXY_WINDOW_EFFECTIVE_WEIGHTS:
                    continue
                expected_weight = INDUSTRY_ETF_PROXY_WINDOW_EFFECTIVE_WEIGHTS[role]
            elif label.get("label_type") == "stock_price_proxy":
                expected_weight = STOCK_PRICE_PROXY_WINDOW_EFFECTIVE_WEIGHTS.get(
                    int(label.get("horizon_days") or 0)
                )
                if expected_weight is None:
                    continue
            else:
                continue
            actual_weight = _float_or_none(label.get("effective_n_weight"))
            if actual_weight is None or abs(actual_weight - expected_weight) > 0.000001:
                overlap_failures.append(
                    f"{label.get('outcome_id')}: {label.get('label_type')} {role} window effective_n_weight must be {expected_weight}"
                )
    checks.append(
        _audit_check(
            check_id="RI-STAT-03",
            requirement=(
                "Overlapping 20/60/120 day ETF windows are retained as separate "
                "evidence but downweighted so one report cannot count as three independent samples."
            ),
            evidence={
                "outcome_window_set_count": len(grouped_labels),
                "complete_industry_etf_window_set_count": complete_window_set_count,
                "complete_stock_price_window_set_count": complete_stock_window_set_count,
                "window_effective_weights": dict(
                    INDUSTRY_ETF_PROXY_WINDOW_EFFECTIVE_WEIGHTS
                ),
                "stock_window_effective_weights": {
                    str(key): value
                    for key, value in STOCK_PRICE_PROXY_WINDOW_EFFECTIVE_WEIGHTS.items()
                },
            },
            failures=overlap_failures,
        )
    )

    ledger_failures: list[str] = []
    ledger_by_claim_id = {
        str(row.get("forecast_claim_id") or ""): row
        for row in forecast_ledger_rows
        if str(row.get("forecast_claim_id") or "").strip()
    }
    for index, row in enumerate(forecast_ledger_rows, 1):
        for field in (
            "forecast_family_id",
            "dedup_cluster_id",
            "consensus_cluster_id",
            "copying_risk_bucket",
        ):
            if not str(row.get(field) or "").strip():
                ledger_failures.append(
                    f"report_forecast_ledger row {index}: {field} required"
                )
        if "independent_viewpoint_count" not in row:
            ledger_failures.append(
                f"report_forecast_ledger row {index}: independent_viewpoint_count field required"
            )
    for index, label in enumerate(outcome_label_rows, 1):
        claim_id = str(label.get("forecast_claim_id") or "")
        ledger = ledger_by_claim_id.get(claim_id)
        label_id = str(label.get("outcome_id") or f"row-{index}")
        if ledger is None:
            ledger_failures.append(f"{label_id}: forecast ledger row missing")
            continue
        if label.get("forecast_family_id") != ledger.get("forecast_family_id"):
            ledger_failures.append(
                f"{label_id}: forecast_family_id must match forecast ledger"
            )
    retrieved_claims = _iter_context_retrieved_claims(weighted_research_context_rows)
    for index, claim in enumerate(retrieved_claims, 1):
        for field in ("forecast_family_id", "dedup_cluster_id", "consensus_cluster_id"):
            if not str(claim.get(field) or "").strip():
                ledger_failures.append(
                    f"retrieved_claims row {index}: {field} required"
                )
        if (
            claim.get("independent_confirmation_policy")
            != "consensus_cluster_not_independent_confirmation"
        ):
            ledger_failures.append(
                f"retrieved_claims row {index}: consensus cluster must not be counted as independent confirmation"
            )
    checks.append(
        _audit_check(
            check_id="RI-STAT-04",
            requirement=(
                "Forecast family IDs define multiple-testing families and consensus/dedup "
                "clusters prevent copied or correlated research from inflating evidence."
            ),
            evidence={
                "forecast_ledger_rows": len(forecast_ledger_rows),
                "multiple_testing_family_count": len(
                    {
                        str(row.get("forecast_family_id") or "")
                        for row in forecast_ledger_rows
                        if str(row.get("forecast_family_id") or "").strip()
                    }
                ),
                "consensus_cluster_count": len(
                    {
                        str(row.get("consensus_cluster_id") or "")
                        for row in forecast_ledger_rows
                        if str(row.get("consensus_cluster_id") or "").strip()
                    }
                ),
                "retrieved_claim_rows": len(retrieved_claims),
            },
            failures=ledger_failures,
        )
    )

    calibration_failures: list[str] = []
    calibration_unavailable_profile_count = 0
    for index, profile in enumerate(all_profile_rows, 1):
        profile_id = str(
            profile.get("profile_id")
            or profile.get("viewpoint_profile_id")
            or f"row-{index}"
        )
        calibration = profile.get("calibration_error")
        if calibration is None:
            calibration_unavailable_profile_count += 1
            if promoted_runtime:
                calibration_failures.append(
                    f"{profile_id}: calibration_error required before promoted runtime"
                )
        elif _float_or_none(calibration) is None:
            calibration_failures.append(
                f"{profile_id}: calibration_error must be numeric or null"
            )
    for index, label in enumerate(outcome_label_rows, 1):
        label_id = str(label.get("outcome_id") or f"row-{index}")
        if _float_or_none(label.get("after_cost_alpha")) is None:
            calibration_failures.append(f"{label_id}: after_cost_alpha missing")
        if (
            label.get("performance_value_basis") == "directional_after_cost_return"
            and _float_or_none(label.get("directional_after_cost_return")) is None
        ):
            calibration_failures.append(
                f"{label_id}: directional_after_cost_return missing"
            )
    checks.append(
        _audit_check(
            check_id="RI-STAT-05",
            requirement=(
                "Scored outcomes and profile weights use after-cost metrics; missing "
                "calibration metrics are allowed only while report intelligence remains shadow-only."
            ),
            evidence={
                "outcome_label_rows": len(outcome_label_rows),
                "calibration_unavailable_profile_count": calibration_unavailable_profile_count,
                "rollout_mode": rollout_mode,
                "production_use_of_weighted_reports": flags.get(
                    "production_use_of_weighted_reports"
                ),
            },
            failures=calibration_failures,
        )
    )

    temporal_failures: list[str] = []
    temporal_summary_count = 0
    short_miss_long_hit_count = 0
    for group_id, labels in grouped_labels.items():
        if not any(
            label.get("label_type") in REPORT_INTELLIGENCE_PROXY_LABEL_TYPES
            for label in labels
        ):
            continue
        summaries = [
            _ensure_mapping(label.get("temporal_validation_summary"))
            for label in labels
        ]
        for label, summary in zip(labels, summaries):
            if not summary:
                temporal_failures.append(
                    f"{label.get('outcome_id')}: temporal_validation_summary required"
                )
                continue
            temporal_summary_count += 1
            if (
                summary.get("window_evidence_policy")
                != "do_not_collapse_multi_window_outcome_to_single_label"
            ):
                temporal_failures.append(
                    f"{label.get('outcome_id')}: window evidence must not be collapsed"
                )
        long_hits = [
            label
            for label in labels
            if label.get("window_role") == "long" and label.get("directional_hit") is True
        ]
        misses = [label for label in labels if label.get("directional_hit") is False]
        if long_hits and misses:
            short_miss_long_hit_count += 1
            if not all(
                _ensure_mapping(label.get("temporal_validation_summary")).get(
                    "long_window_hit_retained"
                )
                is True
                for label in labels
            ):
                temporal_failures.append(
                    f"{group_id}: long-window hit must be retained when shorter windows miss"
                )
    checks.append(
        _audit_check(
            check_id="RI-STAT-06",
            requirement=(
                "Industry ETF and stock proxy validation preserves temporal evidence: "
                "a long-horizon correct report is retained even if shorter windows miss."
            ),
            evidence={
                "industry_etf_window_set_count": sum(
                    1
                    for labels in grouped_labels.values()
                    if any(label.get("label_type") == "industry_etf_proxy" for label in labels)
                ),
                "stock_price_window_set_count": sum(
                    1
                    for labels in grouped_labels.values()
                    if any(label.get("label_type") == "stock_price_proxy" for label in labels)
                ),
                "temporal_summary_count": temporal_summary_count,
                "short_miss_long_hit_window_set_count": short_miss_long_hit_count,
            },
            failures=temporal_failures,
        )
    )

    promotion_failures: list[str] = []
    non_neutral_retrieved_claim_count = 0
    for index, claim in enumerate(retrieved_claims, 1):
        non_neutral = _non_neutral_weight(claim.get("combined_research_prior_weight"))
        if non_neutral:
            non_neutral_retrieved_claim_count += 1
        if non_neutral and claim.get("performance_context_match") not in {
            "source_profile_match",
            "viewpoint_profile_match",
            "source_and_viewpoint_profile_match",
        }:
            promotion_failures.append(
                f"retrieved_claims row {index}: non-neutral weight requires matched performance context"
            )
        if non_neutral and claim.get("current_data_required") is not True:
            promotion_failures.append(
                f"retrieved_claims row {index}: non-neutral research prior still requires current data"
            )
    if promoted_runtime:
        promotion_failures.append(
            "statistical robustness audit allows report intelligence only through shadow tooling"
        )
    checks.append(
        _audit_check(
            check_id="RI-STAT-07",
            requirement=(
                "Non-neutral report-derived priors remain shadow research context and "
                "cannot be promoted without FDR/reality-check, calibration, current data, "
                "paper trading, and promotion gates."
            ),
            evidence={
                "non_neutral_retrieved_claim_count": non_neutral_retrieved_claim_count,
                "rollout_mode": rollout_mode,
                "fdr_or_reality_check_status": "deferred_until_paper_trading_or_production_candidate",
            },
            failures=promotion_failures,
        )
    )

    blockers = [
        failure
        for check in checks
        for failure in _ensure_list(check.get("failures"))
        if str(failure).strip()
    ]
    return {
        "audit_id": "RKE-REPORT-INTELLIGENCE-STATISTICAL-ROBUSTNESS-AUDIT",
        "run_id": run_id,
        "as_of_datetime": _utc_now(),
        "accepted": not blockers,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "checked_item_count": sum(
            [
                len(forecast_ledger_rows),
                len(outcome_label_rows),
                len(source_performance_profile_rows),
                len(viewpoint_performance_profile_rows),
                len(method_performance_profile_rows),
                len(weighted_research_context_rows),
            ]
        ),
        "checks": checks,
        "policy": (
            "report intelligence statistical evidence must be PIT, after-cost, "
            "overlap-adjusted, grouped by forecast family, deduplicated by consensus "
            "clusters, and kept shadow-only until effective-N, multiple-testing, "
            "calibration, paper-trading, and promotion gates pass"
        ),
    }


def write_report_intelligence_statistical_robustness_audit(
    registry_dir: str | Path,
    *,
    run_id: str = "RIR-STATISTICAL-ROBUSTNESS-AUDIT",
    feature_flags: Mapping[str, Any] | None = None,
    forecast_ledger_rows: Sequence[Mapping[str, Any]] | None = None,
    outcome_label_rows: Sequence[Mapping[str, Any]] | None = None,
    source_performance_profile_rows: Sequence[Mapping[str, Any]] | None = None,
    viewpoint_performance_profile_rows: Sequence[Mapping[str, Any]] | None = None,
    method_performance_profile_rows: Sequence[Mapping[str, Any]] | None = None,
    weighted_research_context_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    registry_path = Path(registry_dir)
    blockers: list[str] = []
    if feature_flags is None:
        feature_flags = _read_registry_json(
            registry_path / "feature_flags.json",
            label="feature_flags",
            blockers=blockers,
        )
    if forecast_ledger_rows is None:
        forecast_ledger_rows = _read_registry_jsonl(
            registry_path / "report_forecast_ledger.jsonl",
            label="report_forecast_ledger",
            blockers=blockers,
        )
    if outcome_label_rows is None:
        outcome_label_rows = _read_registry_jsonl(
            registry_path / "report_outcome_labels.jsonl",
            label="report_outcome_labels",
            blockers=blockers,
        )
    if source_performance_profile_rows is None:
        source_performance_profile_rows = _read_registry_jsonl(
            registry_path / "source_performance_profiles.jsonl",
            label="source_performance_profiles",
            blockers=blockers,
        )
    if viewpoint_performance_profile_rows is None:
        viewpoint_performance_profile_rows = _read_registry_jsonl(
            registry_path / "viewpoint_performance_profiles.jsonl",
            label="viewpoint_performance_profiles",
            blockers=blockers,
        )
    if method_performance_profile_rows is None:
        method_performance_profile_rows = _read_registry_jsonl(
            registry_path / "method_performance_profiles.jsonl",
            label="method_performance_profiles",
            blockers=blockers,
        )
    if weighted_research_context_rows is None:
        weighted_research_context_rows = _read_registry_jsonl(
            registry_path / "weighted_research_contexts.jsonl",
            label="weighted_research_contexts",
            blockers=blockers,
        )
    audit = build_report_intelligence_statistical_robustness_audit(
        run_id=run_id,
        feature_flags=feature_flags,
        forecast_ledger_rows=forecast_ledger_rows,
        outcome_label_rows=outcome_label_rows,
        source_performance_profile_rows=source_performance_profile_rows,
        viewpoint_performance_profile_rows=viewpoint_performance_profile_rows,
        method_performance_profile_rows=method_performance_profile_rows,
        weighted_research_context_rows=weighted_research_context_rows,
        load_blockers=blockers,
    )
    return _write_json(registry_path / "statistical_robustness_audit.json", audit)


def _rows_by_id(
    rows: Sequence[Mapping[str, Any]],
    *,
    id_field: str,
) -> tuple[dict[str, Mapping[str, Any]], list[str]]:
    values: dict[str, Mapping[str, Any]] = {}
    failures: list[str] = []
    for index, row in enumerate(rows, 1):
        row_id = str(row.get(id_field) or "").strip()
        if not row_id:
            failures.append(f"row {index}: {id_field} required")
            continue
        if row_id in values:
            failures.append(f"{id_field} duplicated: {row_id}")
            continue
        values[row_id] = row
    return values, failures


def build_report_intelligence_tool_feasibility_audit(
    *,
    run_id: str,
    feature_flags: Mapping[str, Any],
    metric_rows: Sequence[Mapping[str, Any]],
    tool_coverage_match_rows: Sequence[Mapping[str, Any]],
    tool_gap_rows: Sequence[Mapping[str, Any]],
    data_acquisition_proposal_rows: Sequence[Mapping[str, Any]],
    tool_design_proposal_rows: Sequence[Mapping[str, Any]],
    analysis_recipe_rows: Sequence[Mapping[str, Any]],
    runtime_tool_gap_observation_rows: Sequence[Mapping[str, Any]],
    load_blockers: Sequence[str] = (),
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    checks.append(
        _audit_check(
            check_id="RI-TOOL-00",
            requirement="Required report-intelligence tool feasibility inputs load successfully.",
            evidence={"load_blocker_count": len(load_blockers)},
            failures=load_blockers,
        )
    )

    metric_by_id, metric_id_failures = _rows_by_id(metric_rows, id_field="metric_candidate_id")
    coverage_by_metric_id: dict[str, Mapping[str, Any]] = {}
    coverage_failures = list(metric_id_failures)
    coverage_status_counts: dict[str, int] = {}
    for index, coverage in enumerate(tool_coverage_match_rows, 1):
        coverage_id = str(coverage.get("coverage_id") or f"row-{index}")
        metric_id = str(coverage.get("metric_candidate_id") or "").strip()
        status = str(coverage.get("coverage_status") or "")
        coverage_status_counts[status] = coverage_status_counts.get(status, 0) + 1
        if not metric_id:
            coverage_failures.append(f"{coverage_id}: metric_candidate_id required")
        elif metric_id not in metric_by_id:
            coverage_failures.append(f"{coverage_id}: metric_candidate_id not found")
        elif metric_id in coverage_by_metric_id:
            coverage_failures.append(
                f"{coverage_id}: duplicate coverage for metric_candidate_id {metric_id}"
            )
        else:
            coverage_by_metric_id[metric_id] = coverage
        if status not in REPORT_INTELLIGENCE_TOOL_COVERAGE_STATUSES:
            coverage_failures.append(f"{coverage_id}: unsupported coverage_status {status}")
        if _parse_pit_datetime(coverage.get("last_checked_at")) is None:
            coverage_failures.append(f"{coverage_id}: last_checked_at missing or invalid")
        details = _ensure_mapping(coverage.get("coverage_details"))
        if not details:
            coverage_failures.append(f"{coverage_id}: coverage_details required")
        for field in REPORT_INTELLIGENCE_COVERAGE_DETAIL_FIELDS:
            if not isinstance(details.get(field), bool):
                coverage_failures.append(
                    f"{coverage_id}: coverage_details.{field} must be boolean"
                )
        existing_tool_ids = [
            str(item)
            for item in _ensure_list(coverage.get("existing_tool_ids"))
            if str(item).strip()
        ]
        gaps = [
            str(item)
            for item in _ensure_list(coverage.get("gaps"))
            if str(item).strip()
        ]
        if status == "exact_match":
            if not existing_tool_ids:
                coverage_failures.append(
                    f"{coverage_id}: exact_match requires existing_tool_ids"
                )
            for field in REPORT_INTELLIGENCE_COVERAGE_DETAIL_FIELDS:
                if details.get(field) is not True:
                    coverage_failures.append(
                        f"{coverage_id}: exact_match requires {field}=true"
                    )
            if gaps:
                coverage_failures.append(f"{coverage_id}: exact_match must not have gaps")
        elif status != "retired" and not gaps:
            coverage_failures.append(
                f"{coverage_id}: non-exact active coverage must list gaps"
            )
        if status == "license_blocked" and details.get("license_ok") is not False:
            coverage_failures.append(
                f"{coverage_id}: license_blocked requires license_ok=false"
            )
        if status == "no_pit_history" and details.get("pit_available") is not False:
            coverage_failures.append(
                f"{coverage_id}: no_pit_history requires pit_available=false"
            )
    missing_coverage_metric_ids = sorted(set(metric_by_id) - set(coverage_by_metric_id))
    coverage_failures.extend(
        f"{metric_id}: tool coverage match missing"
        for metric_id in missing_coverage_metric_ids[:50]
    )
    checks.append(
        _audit_check(
            check_id="RI-TOOL-01",
            requirement=(
                "Every metric candidate must have deterministic tool coverage with "
                "explicit PIT, lineage, frequency, unit, lookback, and license fields."
            ),
            evidence={
                "metric_candidate_rows": len(metric_rows),
                "tool_coverage_match_rows": len(tool_coverage_match_rows),
                "coverage_status_counts": dict(sorted(coverage_status_counts.items())),
                "required_coverage_detail_fields": list(
                    REPORT_INTELLIGENCE_COVERAGE_DETAIL_FIELDS
                ),
            },
            failures=coverage_failures,
        )
    )

    tool_gap_by_id, gap_id_failures = _rows_by_id(tool_gap_rows, id_field="tool_gap_id")
    gaps_by_metric_id: dict[str, list[Mapping[str, Any]]] = {}
    gap_failures = list(gap_id_failures)
    gap_priority_counts: dict[str, int] = {}
    for index, gap in enumerate(tool_gap_rows, 1):
        gap_id = str(gap.get("tool_gap_id") or f"row-{index}")
        metric_id = str(gap.get("metric_candidate_id") or "")
        priority = str(gap.get("priority_bucket") or "")
        gap_priority_counts[priority] = gap_priority_counts.get(priority, 0) + 1
        if metric_id and metric_id not in metric_by_id:
            gap_failures.append(f"{gap_id}: metric_candidate_id not found")
        if metric_id:
            gaps_by_metric_id.setdefault(metric_id, []).append(gap)
        if priority not in REPORT_INTELLIGENCE_TOOL_GAP_PRIORITY_BUCKETS:
            gap_failures.append(f"{gap_id}: unsupported priority_bucket {priority}")
        if priority == "urgent":
            gap_failures.append(
                f"{gap_id}: urgent is not allowed before license, PIT, engineering, and validation feasibility are accepted"
            )
        if not _ensure_list(gap.get("priority_reasons")):
            gap_failures.append(f"{gap_id}: priority_reasons required")
        if priority in {"medium", "high", "urgent"} and not _ensure_list(
            gap.get("blocking_issues")
        ):
            gap_failures.append(
                f"{gap_id}: medium/high/urgent gaps require blocking_issues"
            )
        if not str(gap.get("owner") or "").strip():
            gap_failures.append(f"{gap_id}: owner required")
        if str(gap.get("status") or "") not in {
            "proposal_pending",
            "blocked_pending_review",
            "closed",
        }:
            gap_failures.append(f"{gap_id}: unsupported status {gap.get('status')}")
    for metric_id, coverage in coverage_by_metric_id.items():
        status = str(coverage.get("coverage_status") or "")
        if status == "exact_match":
            continue
        if status != "retired" and metric_id not in gaps_by_metric_id:
            gap_failures.append(f"{metric_id}: non-exact coverage missing tool gap")
    checks.append(
        _audit_check(
            check_id="RI-TOOL-02",
            requirement=(
                "Missing, partial, non-PIT, license-blocked, or engineering-blocked "
                "coverage must feed into the tool gap registry with bucketed priority."
            ),
            evidence={
                "tool_gap_rows": len(tool_gap_rows),
                "non_exact_coverage_rows": sum(
                    1
                    for row in tool_coverage_match_rows
                    if row.get("coverage_status") not in {"exact_match", "retired"}
                ),
                "gap_priority_counts": dict(sorted(gap_priority_counts.items())),
                "allowed_priority_buckets": list(
                    REPORT_INTELLIGENCE_TOOL_GAP_PRIORITY_BUCKETS
                ),
            },
            failures=gap_failures,
        )
    )

    data_by_gap_id, data_id_failures = _rows_by_id(
        data_acquisition_proposal_rows,
        id_field="tool_gap_id",
    )
    data_failures = list(data_id_failures)
    for index, proposal in enumerate(data_acquisition_proposal_rows, 1):
        proposal_id = str(proposal.get("data_proposal_id") or f"row-{index}")
        gap_id = str(proposal.get("tool_gap_id") or "")
        gap = tool_gap_by_id.get(gap_id)
        if gap is None:
            data_failures.append(f"{proposal_id}: tool_gap_id not found")
            continue
        if proposal.get("owner") != gap.get("owner"):
            data_failures.append(f"{proposal_id}: owner must match tool gap")
        if proposal.get("source_tool_gap_priority") != gap.get("priority_bucket"):
            data_failures.append(
                f"{proposal_id}: source_tool_gap_priority must match tool gap"
            )
        if not _ensure_list(proposal.get("required_fields")):
            data_failures.append(f"{proposal_id}: required_fields required")
        pit = _ensure_mapping(proposal.get("pit_requirements"))
        license_requirements = _ensure_mapping(proposal.get("license_requirements"))
        if pit.get("timestamp_required") is not True:
            data_failures.append(f"{proposal_id}: pit timestamp_required must be true")
        if not isinstance(pit.get("revision_tracking_required"), bool):
            data_failures.append(
                f"{proposal_id}: revision_tracking_required must be boolean"
            )
        if _float_or_none(pit.get("minimum_history_years")) is None:
            data_failures.append(f"{proposal_id}: minimum_history_years required")
        if not isinstance(pit.get("survivorship_issue"), bool):
            data_failures.append(f"{proposal_id}: survivorship_issue must be boolean")
        if license_requirements.get("internal_model_use") is not True:
            data_failures.append(
                f"{proposal_id}: internal_model_use license requirement must be true"
            )
        if license_requirements.get("derived_metric_storage") is not True:
            data_failures.append(
                f"{proposal_id}: derived_metric_storage license requirement must be true"
            )
        if license_requirements.get("external_redistribution") is not False:
            data_failures.append(
                f"{proposal_id}: external_redistribution must remain false"
            )
        if proposal.get("license_status") not in {
            "approved",
            "pending_review",
            "restricted",
            "prohibited",
        }:
            data_failures.append(f"{proposal_id}: unsupported license_status")
        if proposal.get("pit_feasibility_status") not in {
            "pit_feasible_pending_vendor_review",
            "requires_pit_backfill_review",
            "pit_blocked",
        }:
            data_failures.append(f"{proposal_id}: unsupported pit_feasibility_status")
    for gap_id in tool_gap_by_id:
        if gap_id not in data_by_gap_id:
            data_failures.append(f"{gap_id}: data acquisition proposal missing")
    checks.append(
        _audit_check(
            check_id="RI-TOOL-03",
            requirement=(
                "Every tool gap must have a data acquisition proposal with explicit "
                "PIT, survivorship/restatement, required-field, and license requirements."
            ),
            evidence={
                "data_acquisition_proposal_rows": len(data_acquisition_proposal_rows),
                "tool_gap_rows": len(tool_gap_rows),
            },
            failures=data_failures,
        )
    )

    tool_by_gap_id, tool_id_failures = _rows_by_id(
        tool_design_proposal_rows,
        id_field="tool_gap_id",
    )
    design_failures = list(tool_id_failures)
    for index, proposal in enumerate(tool_design_proposal_rows, 1):
        proposal_id = str(proposal.get("tool_proposal_id") or f"row-{index}")
        gap_id = str(proposal.get("tool_gap_id") or "")
        gap = tool_gap_by_id.get(gap_id)
        if gap is None:
            design_failures.append(f"{proposal_id}: tool_gap_id not found")
            continue
        if proposal.get("owner") != gap.get("owner"):
            design_failures.append(f"{proposal_id}: owner must match tool gap")
        if proposal.get("source_tool_gap_priority") != gap.get("priority_bucket"):
            design_failures.append(
                f"{proposal_id}: source_tool_gap_priority must match tool gap"
            )
        if proposal.get("status") not in {
            "shadow_build_requested",
            "blocked_pending_review",
        }:
            design_failures.append(
                f"{proposal_id}: status must remain shadow or blocked"
            )
        input_parameters = _ensure_mapping(proposal.get("input_parameters"))
        for field in ("market", "as_of_date", "lookback_days"):
            if field not in input_parameters:
                design_failures.append(f"{proposal_id}: input_parameters.{field} required")
        output_schema = _ensure_mapping(proposal.get("output_schema"))
        if "as_of_date" not in output_schema:
            design_failures.append(f"{proposal_id}: output_schema.as_of_date required")
        metrics = [
            item
            for item in _ensure_list(output_schema.get("metrics"))
            if isinstance(item, Mapping)
        ]
        if not metrics:
            design_failures.append(f"{proposal_id}: output_schema.metrics required")
        for metric_index, metric in enumerate(metrics, 1):
            for field in (
                "name",
                "value",
                "unit",
                "freshness_days",
                "pit_valid",
                "fallback",
                "quality_flags",
            ):
                if field not in metric:
                    design_failures.append(
                        f"{proposal_id}: output_schema.metrics[{metric_index}].{field} required"
                    )
        fallback_policy = _ensure_mapping(proposal.get("fallback_policy"))
        fallback_cap = _float_or_none(fallback_policy.get("confidence_cap_if_fallback"))
        if fallback_cap is None or fallback_cap > 0.60:
            design_failures.append(
                f"{proposal_id}: fallback confidence cap must be <= 0.60"
            )
        validation_plan = _ensure_mapping(proposal.get("validation_plan"))
        if (_float_or_none(validation_plan.get("shadow_runtime_days")) or 0.0) < 60:
            design_failures.append(
                f"{proposal_id}: shadow_runtime_days must be at least 60"
            )
        if (_float_or_none(validation_plan.get("required_effective_n")) or 0.0) < 30:
            design_failures.append(
                f"{proposal_id}: required_effective_n must be at least 30"
            )
        if not str(validation_plan.get("primary_metric") or "").strip():
            design_failures.append(f"{proposal_id}: primary_metric required")
        if not _ensure_list(validation_plan.get("secondary_metrics")):
            design_failures.append(f"{proposal_id}: secondary_metrics required")
    for gap_id in tool_gap_by_id:
        if gap_id not in tool_by_gap_id:
            design_failures.append(f"{gap_id}: tool design proposal missing")
    checks.append(
        _audit_check(
            check_id="RI-TOOL-04",
            requirement=(
                "Every tool gap must have a deterministic tool design proposal with "
                "input parameters, output schema, fallback policy, and validation plan."
            ),
            evidence={
                "tool_design_proposal_rows": len(tool_design_proposal_rows),
                "tool_gap_rows": len(tool_gap_rows),
                "minimum_shadow_runtime_days": 60,
                "minimum_required_effective_n": 30,
            },
            failures=design_failures,
        )
    )

    recipe_failures: list[str] = []
    for index, recipe in enumerate(analysis_recipe_rows, 1):
        recipe_id = str(recipe.get("analysis_recipe_id") or f"row-{index}")
        runtime_mode = str(recipe.get("runtime_mode") or "")
        validation_status = str(recipe.get("validation_status") or "")
        if runtime_mode != "shadow_only":
            recipe_failures.append(f"{recipe_id}: runtime_mode must remain shadow_only")
        if validation_status not in {"candidate", "shadow_validated"}:
            recipe_failures.append(
                f"{recipe_id}: validation_status must stay pre-paper-trading"
            )
        if runtime_mode == "shadow_only" and validation_status == "shadow_validated":
            required_tools = [
                str(item)
                for item in _ensure_list(recipe.get("required_tools"))
                if str(item).strip()
            ]
            if not required_tools:
                recipe_failures.append(
                    f"{recipe_id}: shadow_validated recipe requires required_tools"
                )
    gap_ids = set(tool_gap_by_id)
    for index, observation in enumerate(runtime_tool_gap_observation_rows, 1):
        observation_id = str(observation.get("runtime_gap_id") or f"row-{index}")
        gap_id = str(observation.get("suggested_tool_gap_id") or "")
        if gap_id not in gap_ids:
            recipe_failures.append(
                f"{observation_id}: suggested_tool_gap_id missing from registry"
            )
        if observation.get("fallback_used") is not True:
            recipe_failures.append(f"{observation_id}: fallback_used must be true")
        if observation.get("runtime_role") != "gap_observation_only":
            recipe_failures.append(
                f"{observation_id}: runtime_role must be gap_observation_only"
            )
        if observation.get("actionability") != REPORT_INTELLIGENCE_SAFE_ACTIONABILITY:
            recipe_failures.append(
                f"{observation_id}: actionability must block trading"
            )
    checks.append(
        _audit_check(
            check_id="RI-TOOL-05",
            requirement=(
                "Analysis recipes and runtime tool gaps must remain shadow-only; "
                "missing tools use explicit fallback observations that feed the gap registry."
            ),
            evidence={
                "analysis_recipe_rows": len(analysis_recipe_rows),
                "runtime_tool_gap_observation_rows": len(runtime_tool_gap_observation_rows),
                "safe_actionability": REPORT_INTELLIGENCE_SAFE_ACTIONABILITY,
            },
            failures=recipe_failures,
        )
    )

    promotion_failures: list[str] = []
    flags = _ensure_mapping(feature_flags.get("flags"))
    rollout_mode = str(feature_flags.get("rollout_mode") or "")
    exact_coverage_count = coverage_status_counts.get("exact_match", 0)
    production_recipe_count = sum(
        1
        for row in analysis_recipe_rows
        if str(row.get("runtime_mode") or "") in {"paper_trading", "limited_production", "production"}
    )
    if flags.get("production_use_of_weighted_reports") is True:
        promotion_failures.append("production_use_of_weighted_reports must remain false")
    if rollout_mode not in REPORT_INTELLIGENCE_ROLLOUT_MODES:
        promotion_failures.append("rollout_mode must be recognized")
    elif (
        REPORT_INTELLIGENCE_ROLLOUT_MODES.index(rollout_mode)
        > REPORT_INTELLIGENCE_ROLLOUT_MODES.index(REPORT_INTELLIGENCE_MAX_SAFE_ROLLOUT_MODE)
    ):
        promotion_failures.append(
            f"rollout_mode {rollout_mode} exceeds {REPORT_INTELLIGENCE_MAX_SAFE_ROLLOUT_MODE}"
        )
    if production_recipe_count:
        promotion_failures.append(
            "tool feasibility audit allows report-intelligence recipes only through shadow tooling"
        )
    if exact_coverage_count == 0 and production_recipe_count:
        promotion_failures.append("production recipes require exact tool coverage")
    checks.append(
        _audit_check(
            check_id="RI-TOOL-06",
            requirement=(
                "Tool feasibility can propose and shadow-build tools, but cannot promote "
                "recipes or report-derived methods until exact coverage, correctness, "
                "PIT history, license review, validation, paper trading, and rollout gates pass."
            ),
            evidence={
                "rollout_mode": rollout_mode,
                "production_use_of_weighted_reports": flags.get(
                    "production_use_of_weighted_reports"
                ),
                "exact_coverage_count": exact_coverage_count,
                "paper_or_production_recipe_count": production_recipe_count,
            },
            failures=promotion_failures,
        )
    )

    blockers = [
        failure
        for check in checks
        for failure in _ensure_list(check.get("failures"))
        if str(failure).strip()
    ]
    return {
        "audit_id": "RKE-REPORT-INTELLIGENCE-TOOL-FEASIBILITY-AUDIT",
        "run_id": run_id,
        "as_of_datetime": _utc_now(),
        "accepted": not blockers,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "checked_item_count": sum(
            [
                len(metric_rows),
                len(tool_coverage_match_rows),
                len(tool_gap_rows),
                len(data_acquisition_proposal_rows),
                len(tool_design_proposal_rows),
                len(analysis_recipe_rows),
                len(runtime_tool_gap_observation_rows),
            ]
        ),
        "checks": checks,
        "policy": (
            "report-intelligence tool feasibility requires deterministic coverage "
            "records, explicit PIT and license requirements, gap-to-proposal "
            "lineage, checker-validatable output schemas, bounded fallback policy, "
            "and shadow-only runtime until tool correctness and promotion gates pass"
        ),
    }


def write_report_intelligence_tool_feasibility_audit(
    registry_dir: str | Path,
    *,
    run_id: str = "RIR-TOOL-FEASIBILITY-AUDIT",
    feature_flags: Mapping[str, Any] | None = None,
    metric_rows: Sequence[Mapping[str, Any]] | None = None,
    tool_coverage_match_rows: Sequence[Mapping[str, Any]] | None = None,
    tool_gap_rows: Sequence[Mapping[str, Any]] | None = None,
    data_acquisition_proposal_rows: Sequence[Mapping[str, Any]] | None = None,
    tool_design_proposal_rows: Sequence[Mapping[str, Any]] | None = None,
    analysis_recipe_rows: Sequence[Mapping[str, Any]] | None = None,
    runtime_tool_gap_observation_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    registry_path = Path(registry_dir)
    blockers: list[str] = []
    if feature_flags is None:
        feature_flags = _read_registry_json(
            registry_path / "feature_flags.json",
            label="feature_flags",
            blockers=blockers,
        )
    if metric_rows is None:
        metric_rows = _read_registry_jsonl(
            registry_path / "metric_candidates.jsonl",
            label="metric_candidates",
            blockers=blockers,
        )
    if tool_coverage_match_rows is None:
        tool_coverage_match_rows = _read_registry_jsonl(
            registry_path / "tool_coverage_matches.jsonl",
            label="tool_coverage_matches",
            blockers=blockers,
        )
    if tool_gap_rows is None:
        tool_gap_rows = _read_registry_jsonl(
            registry_path / "tool_gaps.jsonl",
            label="tool_gaps",
            blockers=blockers,
        )
    if data_acquisition_proposal_rows is None:
        data_acquisition_proposal_rows = _read_registry_jsonl(
            registry_path / "data_acquisition_proposals.jsonl",
            label="data_acquisition_proposals",
            blockers=blockers,
        )
    if tool_design_proposal_rows is None:
        tool_design_proposal_rows = _read_registry_jsonl(
            registry_path / "tool_design_proposals.jsonl",
            label="tool_design_proposals",
            blockers=blockers,
        )
    if analysis_recipe_rows is None:
        analysis_recipe_rows = _read_registry_jsonl(
            registry_path / "analysis_recipes.jsonl",
            label="analysis_recipes",
            blockers=blockers,
        )
    if runtime_tool_gap_observation_rows is None:
        runtime_tool_gap_observation_rows = _read_registry_jsonl(
            registry_path / "runtime_tool_gap_observations.jsonl",
            label="runtime_tool_gap_observations",
            blockers=blockers,
        )
    audit = build_report_intelligence_tool_feasibility_audit(
        run_id=run_id,
        feature_flags=feature_flags,
        metric_rows=metric_rows,
        tool_coverage_match_rows=tool_coverage_match_rows,
        tool_gap_rows=tool_gap_rows,
        data_acquisition_proposal_rows=data_acquisition_proposal_rows,
        tool_design_proposal_rows=tool_design_proposal_rows,
        analysis_recipe_rows=analysis_recipe_rows,
        runtime_tool_gap_observation_rows=runtime_tool_gap_observation_rows,
        load_blockers=blockers,
    )
    return _write_json(registry_path / "tool_feasibility_audit.json", audit)


def _recipe_id(row: Mapping[str, Any], index: int) -> str:
    return str(row.get("analysis_recipe_id") or row.get("recipe_id") or f"row-{index}")


def _recipe_promotion_requirements_missing(row: Mapping[str, Any]) -> list[str]:
    requirements = {
        str(item).strip().lower()
        for item in _ensure_list(row.get("promotion_requirements"))
        if str(item).strip()
    }
    required_fragments = (
        "tool correctness tests pass",
        "pit backtest pass",
        "paper trading pass",
        "no increase in turnover-adjusted loss",
    )
    return [
        fragment
        for fragment in required_fragments
        if not any(fragment in item for item in requirements)
    ]


def build_report_intelligence_recipe_validation_audit(
    *,
    run_id: str,
    feature_flags: Mapping[str, Any],
    method_rows: Sequence[Mapping[str, Any]],
    analysis_recipe_rows: Sequence[Mapping[str, Any]],
    tool_feasibility_audit: Mapping[str, Any],
    weighted_research_context_rows: Sequence[Mapping[str, Any]],
    runtime_tool_gap_observation_rows: Sequence[Mapping[str, Any]],
    load_blockers: Sequence[str] = (),
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    checks.append(
        _audit_check(
            check_id="RI-RECIPE-00",
            requirement="Required report-intelligence recipe validation inputs load successfully.",
            evidence={"load_blocker_count": len(load_blockers)},
            failures=load_blockers,
        )
    )

    method_by_id, method_id_failures = _rows_by_id(method_rows, id_field="method_pattern_id")
    recipe_by_id, recipe_id_failures = _rows_by_id(
        analysis_recipe_rows,
        id_field="analysis_recipe_id",
    )
    schema_failures = [*method_id_failures, *recipe_id_failures]
    for index, recipe in enumerate(analysis_recipe_rows, 1):
        recipe_id = _recipe_id(recipe, index)
        method_id = str(recipe.get("method_pattern_id") or "").strip()
        if method_id not in method_by_id:
            schema_failures.append(f"{recipe_id}: method_pattern_id not found")
        if not str(recipe.get("version") or "").strip():
            schema_failures.append(f"{recipe_id}: version required")
        steps = [item for item in _ensure_list(recipe.get("steps")) if isinstance(item, Mapping)]
        if not steps:
            schema_failures.append(f"{recipe_id}: steps required")
        required_tools = [
            str(item)
            for item in _ensure_list(recipe.get("required_tools"))
            if str(item).strip()
        ]
        step_tools: list[str] = []
        for step_index, step in enumerate(steps, 1):
            if step.get("step") != step_index:
                schema_failures.append(
                    f"{recipe_id}: steps[{step_index}] must have sequential step number"
                )
            for field in ("tool", "metric", "operation", "interpretation"):
                if not str(step.get(field) or "").strip():
                    schema_failures.append(
                        f"{recipe_id}: steps[{step_index}].{field} required"
                    )
            if str(step.get("tool") or "").strip():
                step_tools.append(str(step.get("tool")))
        missing_step_tools = sorted(set(step_tools) - set(required_tools))
        if missing_step_tools:
            schema_failures.append(
                f"{recipe_id}: required_tools missing step tools "
                + ", ".join(missing_step_tools[:10])
            )
        output_signal = _ensure_mapping(recipe.get("output_signal"))
        output_range = _ensure_list(output_signal.get("range"))
        if len(output_range) != 2 or output_range[0] != -1 or output_range[1] != 1:
            schema_failures.append(f"{recipe_id}: output_signal.range must be [-1, 1]")
        confidence_policy = str(output_signal.get("confidence_policy") or "")
        if "current_data" not in confidence_policy or "validation" not in confidence_policy:
            schema_failures.append(
                f"{recipe_id}: confidence_policy must require current data and validation"
            )
        missing_requirements = _recipe_promotion_requirements_missing(recipe)
        if missing_requirements:
            schema_failures.append(
                f"{recipe_id}: missing promotion requirements "
                + ", ".join(missing_requirements)
            )
    checks.append(
        _audit_check(
            check_id="RI-RECIPE-01",
            requirement=(
                "Candidate recipes must be schema-valid, method-linked, step-ordered, "
                "tool-explicit, and bounded to a checker-validatable output signal."
            ),
            evidence={
                "analysis_recipe_rows": len(analysis_recipe_rows),
                "method_pattern_rows": len(method_rows),
            },
            failures=schema_failures,
        )
    )

    lifecycle_failures: list[str] = []
    status_counts: dict[str, int] = {}
    runtime_counts: dict[str, int] = {}
    allowed_status_runtime = {
        "candidate": {"shadow_only"},
        "shadow_validated": {"shadow_only"},
        "validation_candidate": {"shadow_only", "validation_candidate"},
        "paper_trading_ready": {"paper_trading"},
        "limited_production_ready": {"limited_production"},
        "production_ready": {"production"},
        "deprecated": {"deprecated"},
    }
    for index, recipe in enumerate(analysis_recipe_rows, 1):
        recipe_id = _recipe_id(recipe, index)
        status = str(recipe.get("validation_status") or "")
        runtime_mode = str(recipe.get("runtime_mode") or "")
        status_counts[status] = status_counts.get(status, 0) + 1
        runtime_counts[runtime_mode] = runtime_counts.get(runtime_mode, 0) + 1
        if status not in REPORT_INTELLIGENCE_RECIPE_VALIDATION_STATUSES:
            lifecycle_failures.append(f"{recipe_id}: unsupported validation_status {status}")
        if runtime_mode not in REPORT_INTELLIGENCE_RECIPE_RUNTIME_MODES:
            lifecycle_failures.append(f"{recipe_id}: unsupported runtime_mode {runtime_mode}")
        allowed_runtime = allowed_status_runtime.get(status, set())
        if runtime_mode not in allowed_runtime:
            lifecycle_failures.append(
                f"{recipe_id}: validation_status {status} cannot use runtime_mode {runtime_mode}"
            )
        if runtime_mode in {"paper_trading", "limited_production", "production"}:
            lifecycle_failures.append(
                f"{recipe_id}: report-intelligence recipes cannot promote beyond shadow without explicit gated evidence"
            )
    checks.append(
        _audit_check(
            check_id="RI-RECIPE-02",
            requirement=(
                "Recipe lifecycle states cannot skip gates: candidate/shadow remain "
                "shadow-only, and promoted runtime modes require explicit validation evidence."
            ),
            evidence={
                "validation_status_counts": dict(sorted(status_counts.items())),
                "runtime_mode_counts": dict(sorted(runtime_counts.items())),
                "allowed_runtime_modes": list(REPORT_INTELLIGENCE_RECIPE_RUNTIME_MODES),
            },
            failures=lifecycle_failures,
        )
    )

    shadow_failures: list[str] = []
    for context_index, context in enumerate(weighted_research_context_rows, 1):
        if context.get("research_only") is not True:
            shadow_failures.append(
                f"weighted_research_contexts row {context_index}: research_only must be true"
            )
        if context.get("actionability") != REPORT_INTELLIGENCE_SAFE_ACTIONABILITY:
            shadow_failures.append(
                f"weighted_research_contexts row {context_index}: actionability must block trading"
            )
        for recipe_ref in _ensure_list(context.get("available_analysis_recipes")):
            if not isinstance(recipe_ref, Mapping):
                shadow_failures.append(
                    f"weighted_research_contexts row {context_index}: recipe ref must be object"
                )
                continue
            recipe_id = str(recipe_ref.get("analysis_recipe_id") or "")
            recipe = recipe_by_id.get(recipe_id)
            if recipe is None:
                shadow_failures.append(
                    f"weighted_research_contexts row {context_index}: recipe {recipe_id} missing"
                )
                continue
            if recipe_ref.get("runtime_mode") != recipe.get("runtime_mode"):
                shadow_failures.append(
                    f"weighted_research_contexts row {context_index}: recipe {recipe_id} runtime_mode mismatch"
                )
            if recipe_ref.get("validation_status") != recipe.get("validation_status"):
                shadow_failures.append(
                    f"weighted_research_contexts row {context_index}: recipe {recipe_id} validation_status mismatch"
                )
            if recipe_ref.get("runtime_mode") != "shadow_only":
                shadow_failures.append(
                    f"weighted_research_contexts row {context_index}: recipe {recipe_id} must remain shadow_only"
                )
    for index, observation in enumerate(runtime_tool_gap_observation_rows, 1):
        observation_id = str(observation.get("runtime_gap_id") or f"row-{index}")
        if observation.get("runtime_role") != "gap_observation_only":
            shadow_failures.append(f"{observation_id}: runtime_role must be gap_observation_only")
        if observation.get("allowed_runtime_mode") != "shadow_only":
            shadow_failures.append(f"{observation_id}: allowed_runtime_mode must be shadow_only")
    checks.append(
        _audit_check(
            check_id="RI-RECIPE-03",
            requirement=(
                "Shadow recipes may appear in weighted research contexts only as "
                "research-only, no-trade, as-of registry references."
            ),
            evidence={
                "weighted_context_rows": len(weighted_research_context_rows),
                "runtime_tool_gap_observation_rows": len(runtime_tool_gap_observation_rows),
            },
            failures=shadow_failures,
        )
    )

    validation_candidate_failures: list[str] = []
    validation_candidate_count = 0
    tool_feasibility_accepted = tool_feasibility_audit.get("accepted") is True
    for index, recipe in enumerate(analysis_recipe_rows, 1):
        status = str(recipe.get("validation_status") or "")
        runtime_mode = str(recipe.get("runtime_mode") or "")
        if status != "validation_candidate" and runtime_mode != "validation_candidate":
            continue
        validation_candidate_count += 1
        recipe_id = _recipe_id(recipe, index)
        evidence = _ensure_mapping(recipe.get("validation_evidence"))
        if not tool_feasibility_accepted:
            validation_candidate_failures.append(
                f"{recipe_id}: tool_feasibility_audit must be accepted"
            )
        if evidence.get("all_required_tools_pit_valid") is not True:
            validation_candidate_failures.append(
                f"{recipe_id}: all_required_tools_pit_valid required"
            )
        if (_float_or_none(evidence.get("pit_history_years")) or 0.0) < 5.0:
            validation_candidate_failures.append(
                f"{recipe_id}: pit_history_years must be at least 5"
            )
        if (_float_or_none(evidence.get("effective_n")) or 0.0) < 30.0:
            validation_candidate_failures.append(
                f"{recipe_id}: effective_n must be at least 30"
            )
        if any(
            str(tool).startswith("tool.requested.")
            for tool in _ensure_list(recipe.get("required_tools"))
        ):
            validation_candidate_failures.append(
                f"{recipe_id}: validation_candidate cannot depend on requested tools"
            )
    checks.append(
        _audit_check(
            check_id="RI-RECIPE-04",
            requirement=(
                "Validation-candidate recipes require accepted tool feasibility, PIT "
                "history, enough effective samples, and concrete tools rather than requested placeholders."
            ),
            evidence={
                "validation_candidate_recipe_count": validation_candidate_count,
                "minimum_pit_history_years": 5,
                "minimum_effective_n": 30,
                "tool_feasibility_audit_accepted": tool_feasibility_accepted,
            },
            failures=validation_candidate_failures,
        )
    )

    paper_failures: list[str] = []
    paper_recipe_count = 0
    for index, recipe in enumerate(analysis_recipe_rows, 1):
        runtime_mode = str(recipe.get("runtime_mode") or "")
        if runtime_mode not in {"paper_trading", "limited_production", "production"}:
            continue
        paper_recipe_count += 1
        recipe_id = _recipe_id(recipe, index)
        evidence = _ensure_mapping(recipe.get("validation_evidence"))
        if evidence.get("hardened_validation_passed") is not True:
            paper_failures.append(f"{recipe_id}: hardened_validation_passed required")
        if evidence.get("production_sizing_enabled") is True:
            paper_failures.append(f"{recipe_id}: production sizing must not be enabled")
        if (_float_or_none(evidence.get("after_cost_alpha")) or 0.0) <= 0.0:
            paper_failures.append(f"{recipe_id}: after_cost_alpha must be positive")
        if _float_or_none(evidence.get("calibration_error")) is None:
            paper_failures.append(f"{recipe_id}: calibration_error required")
    checks.append(
        _audit_check(
            check_id="RI-RECIPE-05",
            requirement=(
                "Paper-trading recipes require hardened validation, after-cost metrics, "
                "calibration measurement, and no production sizing."
            ),
            evidence={"paper_or_beyond_recipe_count": paper_recipe_count},
            failures=paper_failures,
        )
    )

    production_failures: list[str] = []
    limited_or_production_count = 0
    for index, recipe in enumerate(analysis_recipe_rows, 1):
        runtime_mode = str(recipe.get("runtime_mode") or "")
        if runtime_mode not in {"limited_production", "production"}:
            continue
        limited_or_production_count += 1
        recipe_id = _recipe_id(recipe, index)
        paper_evidence = _ensure_mapping(recipe.get("paper_trading_evidence"))
        rollout_evidence = _ensure_mapping(recipe.get("rollout_evidence"))
        if (_float_or_none(paper_evidence.get("after_cost_alpha_delta")) or 0.0) <= 0.0:
            production_failures.append(
                f"{recipe_id}: after_cost_alpha_delta must improve"
            )
        calibration_delta = _float_or_none(paper_evidence.get("calibration_error_delta"))
        if calibration_delta is None or calibration_delta >= 0.0:
            production_failures.append(
                f"{recipe_id}: calibration_error_delta must improve"
            )
        if runtime_mode == "production":
            for field in (
                "staged_rollout_passed",
                "monitoring_configured",
                "rollback_configured",
            ):
                if rollout_evidence.get(field) is not True:
                    production_failures.append(f"{recipe_id}: {field} required")
    checks.append(
        _audit_check(
            check_id="RI-RECIPE-06",
            requirement=(
                "Limited production and production recipes require paper-trading "
                "after-cost/calibration improvement plus staged rollout, monitoring, and rollback."
            ),
            evidence={"limited_or_production_recipe_count": limited_or_production_count},
            failures=production_failures,
        )
    )

    guard_failures: list[str] = []
    flags = _ensure_mapping(feature_flags.get("flags"))
    rollout_mode = str(feature_flags.get("rollout_mode") or "")
    if flags.get("production_use_of_weighted_reports") is True:
        guard_failures.append("production_use_of_weighted_reports must remain false")
    if rollout_mode not in REPORT_INTELLIGENCE_ROLLOUT_MODES:
        guard_failures.append("rollout_mode must be recognized")
    elif (
        REPORT_INTELLIGENCE_ROLLOUT_MODES.index(rollout_mode)
        > REPORT_INTELLIGENCE_ROLLOUT_MODES.index(REPORT_INTELLIGENCE_MAX_SAFE_ROLLOUT_MODE)
    ):
        guard_failures.append(
            f"rollout_mode {rollout_mode} exceeds {REPORT_INTELLIGENCE_MAX_SAFE_ROLLOUT_MODE}"
        )
    for index, recipe in enumerate(analysis_recipe_rows, 1):
        recipe_id = _recipe_id(recipe, index)
        forbidden_key = _contains_forbidden_shadow_output_field(recipe)
        if forbidden_key:
            guard_failures.append(
                f"{recipe_id}: forbidden decision-impact field {forbidden_key}"
            )
        confidence_policy = str(
            _ensure_mapping(recipe.get("output_signal")).get("confidence_policy") or ""
        )
        if "actionable" in confidence_policy and "requires_current_data" not in confidence_policy:
            guard_failures.append(
                f"{recipe_id}: actionable confidence policy must require current data"
            )
    checks.append(
        _audit_check(
            check_id="RI-RECIPE-07",
            requirement=(
                "Recipe validation outputs cannot alter decisions, sizing, or actionability "
                "while report intelligence remains shadow-only."
            ),
            evidence={
                "rollout_mode": rollout_mode,
                "production_use_of_weighted_reports": flags.get(
                    "production_use_of_weighted_reports"
                ),
                "checked_recipe_rows": len(analysis_recipe_rows),
            },
            failures=guard_failures,
        )
    )

    blockers = [
        failure
        for check in checks
        for failure in _ensure_list(check.get("failures"))
        if str(failure).strip()
    ]
    return {
        "audit_id": "RKE-REPORT-INTELLIGENCE-RECIPE-VALIDATION-AUDIT",
        "run_id": run_id,
        "as_of_datetime": _utc_now(),
        "accepted": not blockers,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "checked_item_count": sum(
            [
                len(method_rows),
                len(analysis_recipe_rows),
                len(weighted_research_context_rows),
                len(runtime_tool_gap_observation_rows),
            ]
        ),
        "checks": checks,
        "policy": (
            "report-intelligence analysis recipes must move through candidate, "
            "shadow_only, validation_candidate, paper_trading, limited_production, "
            "and production gates without skipping evidence; report-derived recipes "
            "remain research-only until current data, tool correctness, PIT validation, "
            "paper trading, monitoring, and rollback are proven"
        ),
    }


def write_report_intelligence_recipe_validation_audit(
    registry_dir: str | Path,
    *,
    run_id: str = "RIR-RECIPE-VALIDATION-AUDIT",
    feature_flags: Mapping[str, Any] | None = None,
    method_rows: Sequence[Mapping[str, Any]] | None = None,
    analysis_recipe_rows: Sequence[Mapping[str, Any]] | None = None,
    tool_feasibility_audit: Mapping[str, Any] | None = None,
    weighted_research_context_rows: Sequence[Mapping[str, Any]] | None = None,
    runtime_tool_gap_observation_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    registry_path = Path(registry_dir)
    blockers: list[str] = []
    if feature_flags is None:
        feature_flags = _read_registry_json(
            registry_path / "feature_flags.json",
            label="feature_flags",
            blockers=blockers,
        )
    if method_rows is None:
        method_rows = _read_registry_jsonl(
            registry_path / "method_patterns.jsonl",
            label="method_patterns",
            blockers=blockers,
        )
    if analysis_recipe_rows is None:
        analysis_recipe_rows = _read_registry_jsonl(
            registry_path / "analysis_recipes.jsonl",
            label="analysis_recipes",
            blockers=blockers,
        )
    if tool_feasibility_audit is None:
        tool_feasibility_audit = _read_registry_json(
            registry_path / "tool_feasibility_audit.json",
            label="tool_feasibility_audit",
            blockers=blockers,
        )
    if weighted_research_context_rows is None:
        weighted_research_context_rows = _read_registry_jsonl(
            registry_path / "weighted_research_contexts.jsonl",
            label="weighted_research_contexts",
            blockers=blockers,
        )
    if runtime_tool_gap_observation_rows is None:
        runtime_tool_gap_observation_rows = _read_registry_jsonl(
            registry_path / "runtime_tool_gap_observations.jsonl",
            label="runtime_tool_gap_observations",
            blockers=blockers,
        )
    audit = build_report_intelligence_recipe_validation_audit(
        run_id=run_id,
        feature_flags=feature_flags,
        method_rows=method_rows,
        analysis_recipe_rows=analysis_recipe_rows,
        tool_feasibility_audit=tool_feasibility_audit,
        weighted_research_context_rows=weighted_research_context_rows,
        runtime_tool_gap_observation_rows=runtime_tool_gap_observation_rows,
        load_blockers=blockers,
    )
    return _write_json(registry_path / "recipe_validation_audit.json", audit)


def _rate(numerator: int | float, denominator: int | float) -> float | None:
    return round(float(numerator) / float(denominator), 6) if denominator else None


def _profile_effective_n_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    id_field: str,
) -> dict[str, Any]:
    values: list[float] = []
    top: list[dict[str, Any]] = []
    for row in rows:
        try:
            value = float(row.get("n_effective") or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        values.append(value)
        top.append(
            {
                "id": str(row.get(id_field) or ""),
                "n_effective": round(value, 6),
                "bucket": str(row.get("shrunk_performance_bucket") or ""),
                "insufficient_data": bool(row.get("insufficient_data", True)),
            }
        )
    top = sorted(top, key=lambda item: item["n_effective"], reverse=True)[:10]
    return {
        "profile_count": len(rows),
        "nonzero_effective_n_count": sum(1 for value in values if value > 0),
        "max_effective_n": round(max(values), 6) if values else 0.0,
        "top_profiles": top,
    }


def _decay_monitoring_missing_requirements(row: Mapping[str, Any]) -> list[str]:
    monitoring = _ensure_mapping(row.get("decay_monitoring"))
    metrics = {
        str(item).strip()
        for item in _ensure_list(monitoring.get("metrics"))
        if str(item).strip()
    }
    rollback_modes = {
        str(item).strip()
        for item in _ensure_list(monitoring.get("rollback_modes"))
        if str(item).strip()
    }
    missing = [
        f"metric:{metric}"
        for metric in REPORT_INTELLIGENCE_REQUIRED_DECAY_METRICS
        if metric not in metrics
    ]
    missing.extend(
        f"rollback_mode:{mode}"
        for mode in REPORT_INTELLIGENCE_REQUIRED_ROLLBACK_MODES
        if mode not in rollback_modes
    )
    for field in (
        "monitoring_window_days",
        "review_frequency",
        "owner",
        "rollback_rule_ref",
    ):
        if monitoring.get(field) in {None, ""}:
            missing.append(f"field:{field}")
    return missing


def build_report_intelligence_monitoring_report(
    *,
    run_id: str,
    metadata_rows: Sequence[Mapping[str, Any]],
    forecast_rows: Sequence[Mapping[str, Any]],
    outcome_label_rows: Sequence[Mapping[str, Any]],
    source_performance_profile_rows: Sequence[Mapping[str, Any]],
    viewpoint_performance_profile_rows: Sequence[Mapping[str, Any]],
    method_performance_profile_rows: Sequence[Mapping[str, Any]],
    tool_coverage_match_rows: Sequence[Mapping[str, Any]],
    tool_gap_rows: Sequence[Mapping[str, Any]],
    data_acquisition_proposal_rows: Sequence[Mapping[str, Any]],
    tool_design_proposal_rows: Sequence[Mapping[str, Any]],
    analysis_recipe_rows: Sequence[Mapping[str, Any]],
    weighted_research_context_rows: Sequence[Mapping[str, Any]],
    runtime_tool_gap_observation_rows: Sequence[Mapping[str, Any]],
    confidence_impact_monitor: Mapping[str, Any] | None = None,
    rollout_mode: str = REPORT_INTELLIGENCE_ROLLOUT_MODE,
) -> dict[str, Any]:
    weighted_claims = [
        claim
        for context in weighted_research_context_rows
        for claim in _ensure_list(context.get("retrieved_claims"))
        if isinstance(claim, Mapping)
    ]
    weighted_claim_count = len(weighted_claims)
    non_neutral_weight_count = sum(
        1
        for claim in weighted_claims
        if float(claim.get("combined_research_prior_weight") or 1.0) != 1.0
    )
    coverage_counts: dict[str, int] = {}
    for row in tool_coverage_match_rows:
        status = str(row.get("coverage_status") or "unknown")
        coverage_counts[status] = coverage_counts.get(status, 0) + 1
    gap_priority_counts: dict[str, int] = {}
    for row in tool_gap_rows:
        priority = str(row.get("priority_bucket") or "unknown")
        gap_priority_counts[priority] = gap_priority_counts.get(priority, 0) + 1
    open_data_proposals = sum(
        1
        for row in data_acquisition_proposal_rows
        if str(row.get("decision_status") or "") not in {"accepted", "rejected", "closed"}
    )
    accepted_tool_proposals = sum(
        1
        for row in tool_design_proposal_rows
        if str(row.get("status") or "") in {"accepted", "implemented", "paper_trading"}
    )
    shadow_recipes = sum(
        1
        for row in analysis_recipe_rows
        if str(row.get("runtime_mode") or "") == "shadow_only"
    )
    validated_recipes = sum(
        1
        for row in analysis_recipe_rows
        if str(row.get("validation_status") or "") in {"validated", "paper_trading"}
    )
    runtime_fallback_count = sum(
        1 for row in runtime_tool_gap_observation_rows if row.get("fallback_used") is True
    )
    decay_monitored_recipe_ids: list[str] = []
    unmonitored_paper_recipe_ids: list[str] = []
    unmonitored_production_recipe_ids: list[str] = []
    for index, row in enumerate(analysis_recipe_rows, 1):
        runtime_mode = str(row.get("runtime_mode") or "")
        if runtime_mode not in {"paper_trading", "limited_production", "production"}:
            continue
        recipe_id = str(row.get("analysis_recipe_id") or f"row-{index}")
        if _decay_monitoring_missing_requirements(row):
            if runtime_mode == "paper_trading":
                unmonitored_paper_recipe_ids.append(recipe_id)
            else:
                unmonitored_production_recipe_ids.append(recipe_id)
        else:
            decay_monitored_recipe_ids.append(recipe_id)
    production_recipe_count = sum(
        1
        for row in analysis_recipe_rows
        if str(row.get("runtime_mode") or "") == "production"
    )
    limited_production_recipe_count = sum(
        1
        for row in analysis_recipe_rows
        if str(row.get("runtime_mode") or "") == "limited_production"
    )
    paper_trading_recipe_count = sum(
        1
        for row in analysis_recipe_rows
        if str(row.get("runtime_mode") or "") == "paper_trading"
    )
    unmonitored_recipe_count = (
        len(unmonitored_paper_recipe_ids) + len(unmonitored_production_recipe_ids)
    )
    alpha_decay_monitor_ready = unmonitored_recipe_count == 0
    confidence_monitor = _ensure_mapping(confidence_impact_monitor)
    return {
        "monitoring_id": "RKE-REPORT-INTELLIGENCE-MONITORING",
        "run_id": run_id,
        "as_of_datetime": _utc_now(),
        "rollout_mode": rollout_mode,
        "report_corpus": {
            "metadata_rows": len(metadata_rows),
            "forecast_claim_rows": len(forecast_rows),
            "outcome_label_rows": len(outcome_label_rows),
        },
        "report_weighting_monitoring": {
            "weighted_research_calibration_error": None,
            "weighted_vs_unweighted_retrieval_difference": _rate(
                non_neutral_weight_count,
                weighted_claim_count,
            ),
            "source_weight_drift": {
                "non_neutral_profile_count": sum(
                    1
                    for row in source_performance_profile_rows
                    if float(row.get("weight_multiplier") or 1.0) != 1.0
                ),
                "max_effective_n": _profile_effective_n_summary(
                    source_performance_profile_rows,
                    id_field="profile_id",
                )["max_effective_n"],
            },
            "high_weight_source_decay_count": 0,
            "low_weight_source_false_negative_rate": None,
            "consensus_crowding_concentration": None,
            "effective_n_by_source": _profile_effective_n_summary(
                source_performance_profile_rows,
                id_field="profile_id",
            ),
            "effective_n_by_viewpoint": _profile_effective_n_summary(
                viewpoint_performance_profile_rows,
                id_field="viewpoint_profile_id",
            ),
            "effective_n_by_method": _profile_effective_n_summary(
                method_performance_profile_rows,
                id_field="method_profile_id",
            ),
        },
        "tooling_loop_monitoring": {
            "tool_gap_open_count": len(tool_gap_rows),
            "tool_gap_priority_counts": dict(sorted(gap_priority_counts.items())),
            "high_priority_gap_aging_count": 0,
            "tool_proposal_acceptance_rate": _rate(
                accepted_tool_proposals,
                len(tool_design_proposal_rows),
            ),
            "data_proposal_open_count": open_data_proposals,
            "shadow_tool_correctness_failure_rate": None,
            "recipe_validation_pass_rate": _rate(
                validated_recipes,
                len(analysis_recipe_rows),
            ),
            "shadow_recipe_count": shadow_recipes,
            "runtime_fallback_observation_count": runtime_fallback_count,
            "evidence_coverage": {
                "tool_coverage_status_counts": dict(sorted(coverage_counts.items())),
                "metric_candidate_count": len(tool_coverage_match_rows),
                "exact_or_partial_coverage_rate": _rate(
                    sum(
                        count
                        for status, count in coverage_counts.items()
                        if status in {"exact_match", "partial_match", "proxy_available"}
                    ),
                    len(tool_coverage_match_rows),
                ),
            },
            "missing_data_reduction": None,
        },
        "alpha_decay_monitoring": {
            "monitoring_scope": (
                "report_intelligence_recipes_at_paper_trading_or_beyond"
            ),
            "required_decay_metrics": list(REPORT_INTELLIGENCE_REQUIRED_DECAY_METRICS),
            "required_rollback_modes": list(REPORT_INTELLIGENCE_REQUIRED_ROLLBACK_MODES),
            "monitoring_spec_ready": True,
            "live_alpha_decay_monitor_active": production_recipe_count > 0,
            "alpha_decay_monitor_ready": alpha_decay_monitor_ready,
            "blocked_reason": (
                "unmonitored_paper_or_production_recipes"
                if unmonitored_recipe_count
                else "no_live_production_recipe_current_rollout"
            ),
            "paper_trading_recipe_count": paper_trading_recipe_count,
            "limited_production_recipe_count": limited_production_recipe_count,
            "production_recipe_count": production_recipe_count,
            "decay_monitored_recipe_ids": sorted(decay_monitored_recipe_ids),
            "unmonitored_paper_trading_recipe_ids": sorted(unmonitored_paper_recipe_ids),
            "unmonitored_production_recipe_ids": sorted(
                unmonitored_production_recipe_ids
            ),
        },
        "confidence_impact_monitoring": {
            "monitor_id": confidence_monitor.get("monitor_id") or "",
            "observation_count": int(confidence_monitor.get("observation_count") or 0),
            "paper_trading_validated_recipe_count": int(
                confidence_monitor.get("paper_trading_validated_recipe_count") or 0
            ),
            "unvalidated_confidence_impact_count": int(
                confidence_monitor.get("unvalidated_confidence_impact_count") or 0
            ),
            "alpha_decay_watch_count": int(
                confidence_monitor.get("alpha_decay_watch_count") or 0
            ),
            "alpha_decay_fail_count": int(
                confidence_monitor.get("alpha_decay_fail_count") or 0
            ),
            "cost_decay_fail_count": int(
                confidence_monitor.get("cost_decay_fail_count") or 0
            ),
            "calibration_drift_count": int(
                confidence_monitor.get("calibration_drift_count") or 0
            ),
            "aggregate_calibration_drift_count": int(
                confidence_monitor.get("aggregate_calibration_drift_count") or 0
            ),
            "confidence_alpha_correlation": confidence_monitor.get(
                "confidence_alpha_correlation"
            ),
            "confidence_alpha_correlation_status": confidence_monitor.get(
                "confidence_alpha_correlation_status"
            )
            or "insufficient_data",
            "regime_fragile_alpha_count": int(
                confidence_monitor.get("regime_fragile_alpha_count") or 0
            ),
            "recommended_action_counts": _ensure_mapping(
                confidence_monitor.get("recommended_action_counts")
            ),
            "production_decision_impact_allowed": False,
        },
        "policy": (
            "monitoring metrics are diagnostic only; report-derived weights and "
            "recipes remain research priors until validation, paper trading, and "
            "promotion gates pass"
        ),
    }


def _report_intelligence_rollout_at_least(
    rollout_mode: str,
    target_mode: str,
) -> bool:
    if (
        rollout_mode not in REPORT_INTELLIGENCE_ROLLOUT_MODES
        or target_mode not in REPORT_INTELLIGENCE_ROLLOUT_MODES
    ):
        return False
    return REPORT_INTELLIGENCE_ROLLOUT_MODES.index(
        rollout_mode
    ) >= REPORT_INTELLIGENCE_ROLLOUT_MODES.index(target_mode)


def _audit_report_accepted(report: Mapping[str, Any]) -> bool:
    try:
        blocker_count = int(report.get("blocker_count") or 0)
    except (TypeError, ValueError):
        blocker_count = 1
    return report.get("accepted") is True and blocker_count == 0


def _phase_coverage_record(
    *,
    phase_id: str,
    phase_name: str,
    requirement: str,
    evidence_artifacts: Sequence[str],
    evidence_counts: Mapping[str, Any],
    failures: Sequence[str],
    deferred_by_rollout: bool = False,
    deferred_reason: str = "",
) -> dict[str, Any]:
    blockers = [str(item) for item in failures if str(item).strip()]
    status = (
        "blocked"
        if blockers
        else "deferred_by_rollout"
        if deferred_by_rollout
        else "passed"
    )
    return {
        "phase_id": phase_id,
        "phase_name": phase_name,
        "requirement": requirement,
        "status": status,
        "accepted": not blockers,
        "deferred_reason": deferred_reason,
        "failure_count": len(blockers),
        "failures": blockers,
        "evidence_artifacts": list(evidence_artifacts),
        "evidence_counts": dict(evidence_counts),
    }


def _coverage_requirement_check(
    *,
    check_id: str,
    phase_id: str,
    check_type: str,
    requirement: str,
    accepted: bool,
    evidence_artifacts: Sequence[str],
    evidence_counts: Mapping[str, Any] | None = None,
    status: str | None = None,
    blocker: str = "",
) -> dict[str, Any]:
    check_status = status or ("passed" if accepted else "blocked")
    return {
        "check_id": check_id,
        "phase_id": phase_id,
        "check_type": check_type,
        "requirement": requirement,
        "status": check_status,
        "accepted": bool(accepted),
        "blocker": "" if accepted else blocker,
        "evidence_artifacts": list(evidence_artifacts),
        "evidence_counts": dict(evidence_counts or {}),
    }


def build_report_intelligence_patch_v1_5_coverage_report(
    *,
    run_id: str,
    feature_flags: Mapping[str, Any],
    metadata_rows: Sequence[Mapping[str, Any]],
    forecast_rows: Sequence[Mapping[str, Any]],
    footprint_rows: Sequence[Mapping[str, Any]],
    metric_rows: Sequence[Mapping[str, Any]],
    method_rows: Sequence[Mapping[str, Any]],
    tool_coverage_match_rows: Sequence[Mapping[str, Any]],
    tool_gap_rows: Sequence[Mapping[str, Any]],
    data_acquisition_proposal_rows: Sequence[Mapping[str, Any]],
    tool_design_proposal_rows: Sequence[Mapping[str, Any]],
    forecast_ledger_rows: Sequence[Mapping[str, Any]],
    outcome_label_rows: Sequence[Mapping[str, Any]],
    outcome_labeling_readiness: Mapping[str, Any],
    source_performance_profile_rows: Sequence[Mapping[str, Any]],
    viewpoint_performance_profile_rows: Sequence[Mapping[str, Any]],
    method_performance_profile_rows: Sequence[Mapping[str, Any]],
    analysis_recipe_rows: Sequence[Mapping[str, Any]],
    weighted_research_context_rows: Sequence[Mapping[str, Any]],
    runtime_tool_gap_observation_rows: Sequence[Mapping[str, Any]],
    monitoring_report: Mapping[str, Any],
    runtime_safety_audit: Mapping[str, Any],
    pit_leakage_audit: Mapping[str, Any],
    extraction_provenance_audit: Mapping[str, Any],
    statistical_robustness_audit: Mapping[str, Any],
    tool_feasibility_audit: Mapping[str, Any],
    recipe_validation_audit: Mapping[str, Any],
    footprint_review_summary: Mapping[str, Any],
    footprint_error_taxonomy: Mapping[str, Any],
    gold_review_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    flags = _ensure_mapping(feature_flags.get("flags"))
    rollout_mode = str(feature_flags.get("rollout_mode") or "")
    runtime_behavior = str(feature_flags.get("runtime_behavior") or "")
    alpha_decay = _ensure_mapping(monitoring_report.get("alpha_decay_monitoring"))
    required_flag_names = set(REPORT_INTELLIGENCE_FEATURE_FLAGS)
    observed_flag_names = set(flags)
    runtime_safety_accepted = _audit_report_accepted(runtime_safety_audit)
    pit_leakage_accepted = _audit_report_accepted(pit_leakage_audit)
    provenance_accepted = _audit_report_accepted(extraction_provenance_audit)
    statistical_accepted = _audit_report_accepted(statistical_robustness_audit)
    tool_feasibility_accepted = _audit_report_accepted(tool_feasibility_audit)
    recipe_validation_accepted = _audit_report_accepted(recipe_validation_audit)
    footprint_review_accepted = footprint_review_summary.get("accepted") is True
    footprint_quality_passed = (
        footprint_review_summary.get("quality_gate_passed") is True
    )
    gold_review_summary = _ensure_mapping(gold_review_summary)
    gold_review_metrics = _ensure_mapping(gold_review_summary.get("metrics"))
    gold_review_passed = (
        gold_review_summary.get("passed") is True
        and gold_review_summary.get("review_complete") is True
        and int(gold_review_summary.get("reviewed_claims") or 0) >= 500
        and int(gold_review_summary.get("total_documents") or 0) >= 50
        and float(gold_review_metrics.get("claim_precision") or 0.0) >= 0.8
        and float(gold_review_metrics.get("source_span_support_precision") or 0.0)
        >= 0.9
    )
    paper_recipe_count = sum(
        1
        for row in analysis_recipe_rows
        if str(row.get("runtime_mode") or "") == "paper_trading"
    )
    limited_recipe_count = sum(
        1
        for row in analysis_recipe_rows
        if str(row.get("runtime_mode") or "") == "limited_production"
    )
    production_recipe_count = sum(
        1
        for row in analysis_recipe_rows
        if str(row.get("runtime_mode") or "") == "production"
    )
    fallback_observation_count = sum(
        1 for row in runtime_tool_gap_observation_rows if row.get("fallback_used") is True
    )
    coverage_counts: dict[str, int] = {}
    for row in tool_coverage_match_rows:
        status = str(row.get("coverage_status") or "unknown")
        coverage_counts[status] = coverage_counts.get(status, 0) + 1
    proposal_gap_ids = {
        str(row.get("tool_gap_id") or "")
        for row in data_acquisition_proposal_rows
        if str(row.get("tool_gap_id") or "").strip()
    }
    design_gap_ids = {
        str(row.get("tool_gap_id") or "")
        for row in tool_design_proposal_rows
        if str(row.get("tool_gap_id") or "").strip()
    }
    gap_ids = {
        str(row.get("tool_gap_id") or "")
        for row in tool_gap_rows
        if str(row.get("tool_gap_id") or "").strip()
    }

    phases: list[dict[str, Any]] = []

    phase_a_failures: list[str] = []
    missing_flags = sorted(required_flag_names - observed_flag_names)
    if rollout_mode not in REPORT_INTELLIGENCE_ROLLOUT_MODES:
        phase_a_failures.append("feature_flags.rollout_mode is not recognized")
    if missing_flags:
        phase_a_failures.append(
            "feature_flags.flags missing expected booleans: "
            + ", ".join(missing_flags)
        )
    if flags.get("production_use_of_weighted_reports") is True:
        phase_a_failures.append("production_use_of_weighted_reports must remain false")
    if "no agent decision impact" not in runtime_behavior:
        phase_a_failures.append(
            "feature_flags.runtime_behavior must state no agent decision impact"
        )
    if not runtime_safety_accepted:
        phase_a_failures.append("runtime_safety_audit must be accepted")
    phases.append(
        _phase_coverage_record(
            phase_id="A",
            phase_name="Schema migration and feature flags",
            requirement=(
                "Add report-intelligence schemas, feature flags, and no-op runtime "
                "guardrails without changing v1.2 actionability."
            ),
            evidence_artifacts=[
                "registry/report_intelligence/feature_flags.json",
                "registry/report_intelligence/runtime_safety_audit.json",
            ],
            evidence_counts={
                "expected_schema_artifacts": list(
                    REPORT_INTELLIGENCE_PATCH_V1_5_SCHEMA_ARTIFACTS
                ),
                "expected_schema_artifact_count": len(
                    REPORT_INTELLIGENCE_PATCH_V1_5_SCHEMA_ARTIFACTS
                ),
                "rollout_mode": rollout_mode,
                "flag_count": len(flags),
                "runtime_safety_audit_accepted": runtime_safety_accepted,
            },
            failures=phase_a_failures,
        )
    )

    phase_b_failures: list[str] = []
    if not forecast_rows:
        phase_b_failures.append("forecast_claims must contain extracted claims")
    if not footprint_rows:
        phase_b_failures.append(
            "analytical_footprints must contain extracted footprints"
        )
    if not footprint_review_accepted:
        phase_b_failures.append(
            "analytical_footprint_review_summary accepted must be true"
        )
    if not footprint_quality_passed:
        phase_b_failures.append(
            "analytical_footprint_review_summary quality_gate_passed must be true"
        )
    if not gold_review_passed:
        phase_b_failures.append(
            "human-labeled forecast claim gold set gate must pass"
        )
    error_tags = [
        item
        for item in _ensure_list(footprint_error_taxonomy.get("error_tags"))
        if isinstance(item, Mapping)
    ]
    if not error_tags:
        phase_b_failures.append(
            "analytical_footprint_error_taxonomy must define reviewable error tags"
        )
    if not provenance_accepted:
        phase_b_failures.append("extraction_provenance_audit must be accepted")
    phases.append(
        _phase_coverage_record(
            phase_id="B",
            phase_name="Extraction and labeling gold sets",
            requirement=(
                "Extract source-grounded forecast claims and analytical footprints, "
                "separate inferred fields, and gate footprint quality through review."
            ),
            evidence_artifacts=[
                "registry/gold_sets/tushare_research_reports.review_summary.json",
                "registry/gold_sets/tushare_research_reports.review_template.jsonl",
                "registry/report_intelligence/forecast_claims.jsonl",
                "registry/report_intelligence/analytical_footprints.jsonl",
                "registry/report_intelligence/analytical_footprint_review_summary.json",
                "registry/report_intelligence/analytical_footprint_error_taxonomy.json",
                "registry/report_intelligence/extraction_provenance_audit.json",
            ],
            evidence_counts={
                "forecast_claim_rows": len(forecast_rows),
                "analytical_footprint_rows": len(footprint_rows),
                "footprint_review_accepted": footprint_review_accepted,
                "footprint_quality_passed": footprint_quality_passed,
                "gold_review_passed": gold_review_passed,
                "gold_reviewed_claims": int(
                    gold_review_summary.get("reviewed_claims") or 0
                ),
                "gold_reviewed_documents": int(
                    gold_review_summary.get("total_documents") or 0
                ),
                "gold_claim_precision": gold_review_metrics.get("claim_precision"),
                "gold_source_span_support_precision": gold_review_metrics.get(
                    "source_span_support_precision"
                ),
                "error_tag_count": len(error_tags),
                "provenance_audit_accepted": provenance_accepted,
            },
            failures=phase_b_failures,
        )
    )

    phase_c_failures: list[str] = []
    if not forecast_ledger_rows:
        phase_c_failures.append("report_forecast_ledger must contain forecast rows")
    if len(forecast_ledger_rows) != len(forecast_rows):
        phase_c_failures.append("report_forecast_ledger row count must match claims")
    if not outcome_label_rows and int(
        outcome_labeling_readiness.get("proxy_label_ready_count") or 0
    ) == 0:
        phase_c_failures.append(
            "outcome labels or governed proxy-label-ready claims are required"
        )
    if not source_performance_profile_rows:
        phase_c_failures.append("source performance profiles must be materialized")
    if not viewpoint_performance_profile_rows:
        phase_c_failures.append("viewpoint performance profiles must be materialized")
    if not method_performance_profile_rows:
        phase_c_failures.append("method performance profiles must be materialized")
    if not statistical_accepted:
        phase_c_failures.append("statistical_robustness_audit must be accepted")
    if flags.get("production_use_of_weighted_reports") is True:
        phase_c_failures.append("backtest MVP cannot enable production use")
    phases.append(
        _phase_coverage_record(
            phase_id="C",
            phase_name="Historical report performance backtest MVP",
            requirement=(
                "Build the report forecast ledger, outcome/proxy labels, performance "
                "profiles, shrinkage evidence, and keep them non-production."
            ),
            evidence_artifacts=[
                "registry/report_intelligence/report_forecast_ledger.jsonl",
                "registry/report_intelligence/report_outcome_labels.jsonl",
                "registry/report_intelligence/outcome_labeling_readiness.json",
                "registry/report_intelligence/source_performance_profiles.jsonl",
                "registry/report_intelligence/viewpoint_performance_profiles.jsonl",
                "registry/report_intelligence/method_performance_profiles.jsonl",
                "registry/report_intelligence/statistical_robustness_audit.json",
            ],
            evidence_counts={
                "forecast_ledger_rows": len(forecast_ledger_rows),
                "outcome_label_rows": len(outcome_label_rows),
                "proxy_label_ready_count": int(
                    outcome_labeling_readiness.get("proxy_label_ready_count") or 0
                ),
                "source_profile_rows": len(source_performance_profile_rows),
                "viewpoint_profile_rows": len(viewpoint_performance_profile_rows),
                "method_profile_rows": len(method_performance_profile_rows),
                "statistical_audit_accepted": statistical_accepted,
            },
            failures=phase_c_failures,
        )
    )

    phase_d_failures: list[str] = []
    if not footprint_rows:
        phase_d_failures.append("analytical footprint registry must not be empty")
    if not metric_rows:
        phase_d_failures.append("metric candidate registry must not be empty")
    if not method_rows:
        phase_d_failures.append("method pattern registry must not be empty")
    if not footprint_review_accepted or not footprint_quality_passed:
        phase_d_failures.append("analytical footprint review quality gate must pass")
    if not provenance_accepted:
        phase_d_failures.append("source-grounding provenance audit must pass")
    phases.append(
        _phase_coverage_record(
            phase_id="D",
            phase_name="Analytical footprint extraction and registry build",
            requirement=(
                "Normalize source-grounded or explicitly inferred footprints, metric "
                "candidates, method patterns, aliases, and license-aware storage."
            ),
            evidence_artifacts=[
                "registry/report_intelligence/analytical_footprints.jsonl",
                "registry/report_intelligence/metric_candidates.jsonl",
                "registry/report_intelligence/method_patterns.jsonl",
                "registry/report_intelligence/analytical_footprint_review_summary.json",
            ],
            evidence_counts={
                "analytical_footprint_rows": len(footprint_rows),
                "metric_candidate_rows": len(metric_rows),
                "method_pattern_rows": len(method_rows),
                "footprint_review_accepted": footprint_review_accepted,
                "footprint_quality_passed": footprint_quality_passed,
            },
            failures=phase_d_failures,
        )
    )

    phase_e_failures: list[str] = []
    if not metric_rows:
        phase_e_failures.append("metric candidate rows are required")
    if len(tool_coverage_match_rows) < len(metric_rows):
        phase_e_failures.append(
            "tool coverage rows must cover every metric candidate"
        )
    if not gap_ids:
        phase_e_failures.append("tool gap registry must contain reviewable gaps")
    missing_data_proposals = sorted(gap_ids - proposal_gap_ids)
    missing_tool_proposals = sorted(gap_ids - design_gap_ids)
    if missing_data_proposals:
        phase_e_failures.append(
            "tool gaps missing data acquisition proposals: "
            + ", ".join(missing_data_proposals[:20])
        )
    if missing_tool_proposals:
        phase_e_failures.append(
            "tool gaps missing tool design proposals: "
            + ", ".join(missing_tool_proposals[:20])
        )
    if not tool_feasibility_accepted:
        phase_e_failures.append("tool_feasibility_audit must be accepted")
    phases.append(
        _phase_coverage_record(
            phase_id="E",
            phase_name="Tool coverage and gap registry",
            requirement=(
                "Map MVP metrics to current tools, rank PIT/license-aware gaps, "
                "and generate data/tool proposals for review."
            ),
            evidence_artifacts=[
                "registry/report_intelligence/tool_coverage_matches.jsonl",
                "registry/report_intelligence/tool_gaps.jsonl",
                "registry/report_intelligence/data_acquisition_proposals.jsonl",
                "registry/report_intelligence/tool_design_proposals.jsonl",
                "registry/report_intelligence/tool_feasibility_audit.json",
            ],
            evidence_counts={
                "metric_candidate_rows": len(metric_rows),
                "tool_coverage_match_rows": len(tool_coverage_match_rows),
                "tool_coverage_status_counts": dict(sorted(coverage_counts.items())),
                "tool_gap_rows": len(tool_gap_rows),
                "data_acquisition_proposal_rows": len(
                    data_acquisition_proposal_rows
                ),
                "tool_design_proposal_rows": len(tool_design_proposal_rows),
                "tool_feasibility_audit_accepted": tool_feasibility_accepted,
            },
            failures=phase_e_failures,
        )
    )

    phase_f_failures: list[str] = []
    if not _report_intelligence_rollout_at_least(rollout_mode, "shadow_tooling"):
        phase_f_failures.append("rollout_mode must reach shadow_tooling for Phase F")
    if not weighted_research_context_rows:
        phase_f_failures.append("weighted research contexts are required")
    if not analysis_recipe_rows:
        phase_f_failures.append("analysis recipes are required")
    if not runtime_tool_gap_observation_rows:
        phase_f_failures.append("runtime tool gap observations are required")
    if fallback_observation_count != len(runtime_tool_gap_observation_rows):
        phase_f_failures.append(
            "runtime tool gap observations must be fallback/gap-observation only"
        )
    if not runtime_safety_accepted:
        phase_f_failures.append("runtime_safety_audit must be accepted")
    if not pit_leakage_accepted:
        phase_f_failures.append("pit_leakage_audit must be accepted")
    if not recipe_validation_accepted:
        phase_f_failures.append("recipe_validation_audit must be accepted")
    phases.append(
        _phase_coverage_record(
            phase_id="F",
            phase_name="Shadow runtime",
            requirement=(
                "Run weighted research retrieval, shadow-only recipes, and runtime "
                "tool-gap feedback without changing agent decisions."
            ),
            evidence_artifacts=[
                "registry/report_intelligence/weighted_research_contexts.jsonl",
                "registry/report_intelligence/analysis_recipes.jsonl",
                "registry/report_intelligence/runtime_tool_gap_observations.jsonl",
                "registry/report_intelligence/runtime_safety_audit.json",
                "registry/report_intelligence/pit_leakage_audit.json",
                "registry/report_intelligence/recipe_validation_audit.json",
            ],
            evidence_counts={
                "rollout_mode": rollout_mode,
                "weighted_research_context_rows": len(
                    weighted_research_context_rows
                ),
                "analysis_recipe_rows": len(analysis_recipe_rows),
                "runtime_tool_gap_observation_rows": len(
                    runtime_tool_gap_observation_rows
                ),
                "fallback_observation_count": fallback_observation_count,
                "runtime_safety_audit_accepted": runtime_safety_accepted,
                "pit_leakage_audit_accepted": pit_leakage_accepted,
                "recipe_validation_audit_accepted": recipe_validation_accepted,
            },
            failures=phase_f_failures,
        )
    )

    phase_g_deferred = not _report_intelligence_rollout_at_least(
        rollout_mode,
        "paper_trading",
    )
    phase_g_failures: list[str] = []
    if phase_g_deferred:
        if paper_recipe_count != 0:
            phase_g_failures.append(
                "paper_trading recipes must be absent while rollout is below paper_trading"
            )
        if not recipe_validation_accepted:
            phase_g_failures.append("recipe_validation_audit must be accepted")
        if alpha_decay.get("alpha_decay_monitor_ready") is not True:
            phase_g_failures.append(
                "alpha_decay_monitoring alpha_decay_monitor_ready must be true"
            )
    else:
        if paper_recipe_count == 0:
            phase_g_failures.append(
                "paper_trading rollout requires at least one paper_trading recipe"
            )
        if not recipe_validation_accepted:
            phase_g_failures.append("recipe_validation_audit must be accepted")
        if alpha_decay.get("alpha_decay_monitor_ready") is not True:
            phase_g_failures.append("paper_trading recipes require decay monitoring")
    phases.append(
        _phase_coverage_record(
            phase_id="G",
            phase_name="Paper trading integration",
            requirement=(
                "Promote selected recipes only after paper-trading validation, "
                "after-cost/calibration monitoring, and confidence-impact checks."
            ),
            evidence_artifacts=[
                "registry/report_intelligence/recipe_validation_audit.json",
                "registry/report_intelligence/monitoring_report.json",
            ],
            evidence_counts={
                "rollout_mode": rollout_mode,
                "paper_trading_recipe_count": paper_recipe_count,
                "recipe_validation_audit_accepted": recipe_validation_accepted,
                "alpha_decay_monitor_ready": alpha_decay.get(
                    "alpha_decay_monitor_ready"
                ),
                "unmonitored_paper_trading_recipe_ids": alpha_decay.get(
                    "unmonitored_paper_trading_recipe_ids",
                    [],
                ),
            },
            failures=phase_g_failures,
            deferred_by_rollout=phase_g_deferred,
            deferred_reason=(
                "current rollout is shadow_tooling; Phase G is intentionally gated"
                if phase_g_deferred
                else ""
            ),
        )
    )

    phase_h_deferred = not _report_intelligence_rollout_at_least(
        rollout_mode,
        "limited_production",
    )
    observed_rollback_modes = {
        str(item)
        for item in _ensure_list(alpha_decay.get("required_rollback_modes"))
        if str(item).strip()
    }
    missing_rollback_modes = sorted(
        set(REPORT_INTELLIGENCE_REQUIRED_ROLLBACK_MODES) - observed_rollback_modes
    )
    phase_h_failures: list[str] = []
    if missing_rollback_modes:
        phase_h_failures.append(
            "alpha_decay_monitoring missing rollback modes: "
            + ", ".join(missing_rollback_modes)
        )
    if not runtime_safety_accepted:
        phase_h_failures.append("runtime_safety_audit must be accepted")
    if not pit_leakage_accepted:
        phase_h_failures.append("pit_leakage_audit must be accepted")
    if alpha_decay.get("monitoring_spec_ready") is not True:
        phase_h_failures.append("alpha_decay_monitoring monitoring_spec_ready required")
    if phase_h_deferred:
        if limited_recipe_count or production_recipe_count:
            phase_h_failures.append(
                "limited/production recipes must be absent below limited_production rollout"
            )
        if flags.get("production_use_of_weighted_reports") is True:
            phase_h_failures.append(
                "production_use_of_weighted_reports must remain false"
            )
    else:
        if limited_recipe_count + production_recipe_count == 0:
            phase_h_failures.append(
                "limited_production rollout requires a limited or production recipe"
            )
        if not recipe_validation_accepted:
            phase_h_failures.append("recipe_validation_audit must be accepted")
        if alpha_decay.get("alpha_decay_monitor_ready") is not True:
            phase_h_failures.append("limited production requires decay monitoring")
    phases.append(
        _phase_coverage_record(
            phase_id="H",
            phase_name="Limited production rollout",
            requirement=(
                "Allow limited production only after strict actionability, leakage, "
                "license, rollback, monitoring, and staged rollout gates pass."
            ),
            evidence_artifacts=[
                "registry/report_intelligence/runtime_safety_audit.json",
                "registry/report_intelligence/pit_leakage_audit.json",
                "registry/report_intelligence/monitoring_report.json",
                "registry/report_intelligence/recipe_validation_audit.json",
            ],
            evidence_counts={
                "rollout_mode": rollout_mode,
                "limited_production_recipe_count": limited_recipe_count,
                "production_recipe_count": production_recipe_count,
                "production_use_of_weighted_reports": flags.get(
                    "production_use_of_weighted_reports"
                ),
                "monitoring_spec_ready": alpha_decay.get("monitoring_spec_ready"),
                "required_rollback_modes": sorted(observed_rollback_modes),
                "runtime_safety_audit_accepted": runtime_safety_accepted,
                "pit_leakage_audit_accepted": pit_leakage_accepted,
            },
            failures=phase_h_failures,
            deferred_by_rollout=phase_h_deferred,
            deferred_reason=(
                "current rollout is shadow_tooling; Phase H is intentionally gated"
                if phase_h_deferred
                else ""
            ),
        )
    )

    blockers = [
        f"Phase {phase['phase_id']}: {failure}"
        for phase in phases
        for failure in _ensure_list(phase.get("failures"))
    ]
    passed_phase_ids = [
        str(phase["phase_id"]) for phase in phases if phase.get("status") == "passed"
    ]
    deferred_phase_ids = [
        str(phase["phase_id"])
        for phase in phases
        if phase.get("status") == "deferred_by_rollout"
    ]
    blocked_phase_ids = [
        str(phase["phase_id"]) for phase in phases if phase.get("status") == "blocked"
    ]
    precision_recall = _ensure_mapping(
        footprint_review_summary.get("precision_recall_report")
    )
    requirement_checklist = [
        _coverage_requirement_check(
            check_id="RI15-A-D1",
            phase_id="A",
            check_type="deliverable",
            requirement=(
                "report_metadata, forecast_claim, analytical_footprint, ledger, "
                "outcome-label, performance-profile, metric, method, tool-gap, "
                "proposal, and analysis_recipe schemas are registered."
            ),
            accepted=(
                len(REPORT_INTELLIGENCE_PATCH_V1_5_SCHEMA_ARTIFACTS) >= 15
            ),
            evidence_artifacts=[
                f"schemas/{name}"
                for name in REPORT_INTELLIGENCE_PATCH_V1_5_SCHEMA_ARTIFACTS
            ],
            evidence_counts={
                "expected_schema_artifact_count": len(
                    REPORT_INTELLIGENCE_PATCH_V1_5_SCHEMA_ARTIFACTS
                )
            },
            blocker="report-intelligence schema artifact set is incomplete",
        ),
        _coverage_requirement_check(
            check_id="RI15-A-D2",
            phase_id="A",
            check_type="acceptance",
            requirement=(
                "Feature flags and runtime no-op mode keep v1.2 runtime unchanged "
                "and forbid report-only actionability."
            ),
            accepted=(
                runtime_safety_accepted
                and flags.get("production_use_of_weighted_reports") is False
                and "no agent decision impact" in runtime_behavior
            ),
            evidence_artifacts=[
                "registry/report_intelligence/feature_flags.json",
                "registry/report_intelligence/runtime_safety_audit.json",
            ],
            evidence_counts={
                "rollout_mode": rollout_mode,
                "runtime_behavior": runtime_behavior,
                "production_use_of_weighted_reports": flags.get(
                    "production_use_of_weighted_reports"
                ),
            },
            blocker="runtime no-op/actionability guard is not proven",
        ),
        _coverage_requirement_check(
            check_id="RI15-B-D1",
            phase_id="B",
            check_type="deliverable",
            requirement=(
                "Human-labeled forecast claim gold set is complete and passes "
                "claim/source-span precision gates."
            ),
            accepted=gold_review_passed,
            evidence_artifacts=[
                "registry/gold_sets/tushare_research_reports.review_summary.json",
                "registry/gold_sets/tushare_research_reports.review_template.jsonl",
            ],
            evidence_counts={
                "reviewed_claims": int(
                    gold_review_summary.get("reviewed_claims") or 0
                ),
                "total_documents": int(
                    gold_review_summary.get("total_documents") or 0
                ),
                "claim_precision": gold_review_metrics.get("claim_precision"),
                "source_span_support_precision": gold_review_metrics.get(
                    "source_span_support_precision"
                ),
            },
            blocker="human-labeled forecast claim gold set has not passed",
        ),
        _coverage_requirement_check(
            check_id="RI15-B-D2",
            phase_id="B",
            check_type="deliverable",
            requirement=(
                "Human-labeled analytical footprint gold set, precision/recall "
                "report, error taxonomy, and span-grounded verifier are present."
            ),
            accepted=(
                footprint_review_accepted
                and footprint_quality_passed
                and bool(precision_recall)
                and bool(error_tags)
                and provenance_accepted
            ),
            evidence_artifacts=[
                "registry/report_intelligence/analytical_footprint_review_summary.json",
                "registry/report_intelligence/analytical_footprint_error_taxonomy.json",
                "registry/report_intelligence/extraction_provenance_audit.json",
            ],
            evidence_counts={
                "footprint_precision": precision_recall.get(
                    "footprint_precision"
                ),
                "span_support_precision": precision_recall.get(
                    "span_support_precision"
                ),
                "recall_status": precision_recall.get("recall_status"),
                "error_tag_count": len(error_tags),
            },
            blocker="analytical-footprint gold set/provenance evidence incomplete",
        ),
        _coverage_requirement_check(
            check_id="RI15-C-D1",
            phase_id="C",
            check_type="deliverable",
            requirement=(
                "Report forecast ledger, PIT outcome labels with overlap "
                "adjustment, source/viewpoint/method profiles, shrinkage, and "
                "bucketed weights are materialized without production use."
            ),
            accepted=(
                bool(forecast_ledger_rows)
                and bool(outcome_label_rows)
                and bool(source_performance_profile_rows)
                and bool(viewpoint_performance_profile_rows)
                and bool(method_performance_profile_rows)
                and statistical_accepted
                and flags.get("production_use_of_weighted_reports") is False
            ),
            evidence_artifacts=[
                "registry/report_intelligence/report_forecast_ledger.jsonl",
                "registry/report_intelligence/report_outcome_labels.jsonl",
                "registry/report_intelligence/source_performance_profiles.jsonl",
                "registry/report_intelligence/viewpoint_performance_profiles.jsonl",
                "registry/report_intelligence/method_performance_profiles.jsonl",
                "registry/report_intelligence/statistical_robustness_audit.json",
            ],
            evidence_counts={
                "forecast_ledger_rows": len(forecast_ledger_rows),
                "outcome_label_rows": len(outcome_label_rows),
                "source_profile_rows": len(source_performance_profile_rows),
                "viewpoint_profile_rows": len(viewpoint_performance_profile_rows),
                "method_profile_rows": len(method_performance_profile_rows),
                "statistical_audit_accepted": statistical_accepted,
            },
            blocker="historical report performance backtest MVP is incomplete",
        ),
        _coverage_requirement_check(
            check_id="RI15-D-D1",
            phase_id="D",
            check_type="deliverable",
            requirement=(
                "Analytical footprints, metric candidates with alias/proxy "
                "mapping, method patterns, and license-aware storage policy are "
                "registered as candidate/shadow assets."
            ),
            accepted=(
                bool(footprint_rows)
                and bool(metric_rows)
                and bool(method_rows)
                and footprint_quality_passed
                and provenance_accepted
            ),
            evidence_artifacts=[
                "registry/report_intelligence/analytical_footprints.jsonl",
                "registry/report_intelligence/metric_candidates.jsonl",
                "registry/report_intelligence/method_patterns.jsonl",
                "registry/report_intelligence/analytical_footprint_review_summary.json",
            ],
            evidence_counts={
                "analytical_footprint_rows": len(footprint_rows),
                "metric_candidate_rows": len(metric_rows),
                "method_pattern_rows": len(method_rows),
            },
            blocker="analytical footprint registry build is incomplete",
        ),
        _coverage_requirement_check(
            check_id="RI15-E-D1",
            phase_id="E",
            check_type="deliverable",
            requirement=(
                "Tool coverage matcher, ranked tool gaps, data availability/PIT "
                "review, data acquisition proposals, and tool design proposals "
                "cover every metric candidate."
            ),
            accepted=(
                bool(metric_rows)
                and len(tool_coverage_match_rows) >= len(metric_rows)
                and bool(gap_ids)
                and not missing_data_proposals
                and not missing_tool_proposals
                and tool_feasibility_accepted
            ),
            evidence_artifacts=[
                "registry/report_intelligence/tool_coverage_matches.jsonl",
                "registry/report_intelligence/tool_gaps.jsonl",
                "registry/report_intelligence/data_acquisition_proposals.jsonl",
                "registry/report_intelligence/tool_design_proposals.jsonl",
                "registry/report_intelligence/tool_feasibility_audit.json",
            ],
            evidence_counts={
                "metric_candidate_rows": len(metric_rows),
                "tool_coverage_match_rows": len(tool_coverage_match_rows),
                "tool_gap_rows": len(tool_gap_rows),
                "data_acquisition_proposal_rows": len(
                    data_acquisition_proposal_rows
                ),
                "tool_design_proposal_rows": len(tool_design_proposal_rows),
            },
            blocker="tool coverage/gap proposal loop is incomplete",
        ),
        _coverage_requirement_check(
            check_id="RI15-F-D1",
            phase_id="F",
            check_type="deliverable",
            requirement=(
                "Weighted research retriever, shadow-only analysis recipes, "
                "runtime tool gap observations, and audit logs run without "
                "changing agent decisions."
            ),
            accepted=(
                _report_intelligence_rollout_at_least(
                    rollout_mode,
                    "shadow_tooling",
                )
                and bool(weighted_research_context_rows)
                and bool(analysis_recipe_rows)
                and bool(runtime_tool_gap_observation_rows)
                and fallback_observation_count
                == len(runtime_tool_gap_observation_rows)
                and runtime_safety_accepted
                and pit_leakage_accepted
                and recipe_validation_accepted
            ),
            evidence_artifacts=[
                "registry/report_intelligence/weighted_research_contexts.jsonl",
                "registry/report_intelligence/analysis_recipes.jsonl",
                "registry/report_intelligence/runtime_tool_gap_observations.jsonl",
                "registry/report_intelligence/runtime_safety_audit.json",
                "registry/report_intelligence/pit_leakage_audit.json",
                "registry/report_intelligence/recipe_validation_audit.json",
            ],
            evidence_counts={
                "rollout_mode": rollout_mode,
                "weighted_research_context_rows": len(
                    weighted_research_context_rows
                ),
                "analysis_recipe_rows": len(analysis_recipe_rows),
                "runtime_tool_gap_observation_rows": len(
                    runtime_tool_gap_observation_rows
                ),
                "fallback_observation_count": fallback_observation_count,
            },
            blocker="shadow runtime loop is incomplete",
        ),
        _coverage_requirement_check(
            check_id="RI15-G-G1",
            phase_id="G",
            check_type="rollout_gate",
            requirement=(
                "Paper trading integration remains gated until selected recipes "
                "have paper-trading validation, after-cost/calibration monitoring, "
                "and confidence-impact checks."
            ),
            accepted=not phase_g_failures,
            evidence_artifacts=[
                "registry/report_intelligence/recipe_validation_audit.json",
                "registry/report_intelligence/monitoring_report.json",
            ],
            evidence_counts={
                "rollout_mode": rollout_mode,
                "paper_trading_recipe_count": paper_recipe_count,
                "alpha_decay_monitor_ready": alpha_decay.get(
                    "alpha_decay_monitor_ready"
                ),
            },
            status="deferred_by_rollout" if phase_g_deferred else None,
            blocker="paper-trading rollout gate failed",
        ),
        _coverage_requirement_check(
            check_id="RI15-H-G1",
            phase_id="H",
            check_type="rollout_gate",
            requirement=(
                "Limited production remains gated by max research adjustment cap, "
                "rollback hooks, alpha decay monitoring, license/PIT safety, and "
                "monthly review policy."
            ),
            accepted=not phase_h_failures,
            evidence_artifacts=[
                "registry/report_intelligence/runtime_safety_audit.json",
                "registry/report_intelligence/pit_leakage_audit.json",
                "registry/report_intelligence/monitoring_report.json",
                "registry/report_intelligence/recipe_validation_audit.json",
            ],
            evidence_counts={
                "rollout_mode": rollout_mode,
                "limited_production_recipe_count": limited_recipe_count,
                "production_recipe_count": production_recipe_count,
                "required_rollback_modes": sorted(observed_rollback_modes),
                "production_use_of_weighted_reports": flags.get(
                    "production_use_of_weighted_reports"
                ),
            },
            status="deferred_by_rollout" if phase_h_deferred else None,
            blocker="limited-production rollout gate failed",
        ),
    ]
    checklist_blockers = [
        f"{item['check_id']}: {item['blocker']}"
        for item in requirement_checklist
        if item.get("accepted") is not True
        and item.get("status") != "deferred_by_rollout"
    ]
    blockers.extend(checklist_blockers)
    return {
        "coverage_report_id": "RKE-REPORT-INTELLIGENCE-PATCH-V1-5-COVERAGE",
        "run_id": run_id,
        "as_of_datetime": _utc_now(),
        "source_plan_path": "MOSAIC_RKE_REPORT_INTELLIGENCE_LOOP_PATCH_V1_5_MERGED.md",
        "current_rollout_mode": rollout_mode,
        "current_completion_scope": (
            "shadow_mvp_with_paper_and_production_phases_gated"
        ),
        "accepted": not blockers,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "phase_count": len(phases),
        "passed_phase_ids": passed_phase_ids,
        "deferred_phase_ids": deferred_phase_ids,
        "blocked_phase_ids": blocked_phase_ids,
        "phase_records": phases,
        "requirement_checklist": requirement_checklist,
        "corpus_counts": {
            "metadata_rows": len(metadata_rows),
            "forecast_claim_rows": len(forecast_rows),
            "analytical_footprint_rows": len(footprint_rows),
            "metric_candidate_rows": len(metric_rows),
            "method_pattern_rows": len(method_rows),
            "tool_gap_rows": len(tool_gap_rows),
            "outcome_label_rows": len(outcome_label_rows),
            "weighted_research_context_rows": len(weighted_research_context_rows),
            "runtime_tool_gap_observation_rows": len(
                runtime_tool_gap_observation_rows
            ),
        },
        "policy": (
            "Phase A-F evidence covers the current shadow MVP. Phase G/H are "
            "accepted only as rollout-gated deferrals until explicit paper-trading "
            "and limited-production evidence exists."
        ),
    }


def write_report_intelligence_patch_v1_5_coverage_report(
    registry_dir: str | Path,
    *,
    run_id: str = "RIR-PATCH-V1-5-COVERAGE",
) -> dict[str, Any]:
    registry_path = Path(registry_dir)
    blockers: list[str] = []
    feature_flags = _read_registry_json(
        registry_path / "feature_flags.json",
        label="feature_flags",
        blockers=blockers,
    )
    metadata_rows = _read_registry_jsonl(
        registry_path / "report_metadata.jsonl",
        label="report_metadata",
        blockers=blockers,
    )
    forecast_rows = _read_registry_jsonl(
        registry_path / "forecast_claims.jsonl",
        label="forecast_claims",
        blockers=blockers,
    )
    footprint_rows = _read_registry_jsonl(
        registry_path / "analytical_footprints.jsonl",
        label="analytical_footprints",
        blockers=blockers,
    )
    metric_rows = _read_registry_jsonl(
        registry_path / "metric_candidates.jsonl",
        label="metric_candidates",
        blockers=blockers,
    )
    method_rows = _read_registry_jsonl(
        registry_path / "method_patterns.jsonl",
        label="method_patterns",
        blockers=blockers,
    )
    tool_coverage_match_rows = _read_registry_jsonl(
        registry_path / "tool_coverage_matches.jsonl",
        label="tool_coverage_matches",
        blockers=blockers,
    )
    tool_gap_rows = _read_registry_jsonl(
        registry_path / "tool_gaps.jsonl",
        label="tool_gaps",
        blockers=blockers,
    )
    data_acquisition_proposal_rows = _read_registry_jsonl(
        registry_path / "data_acquisition_proposals.jsonl",
        label="data_acquisition_proposals",
        blockers=blockers,
    )
    tool_design_proposal_rows = _read_registry_jsonl(
        registry_path / "tool_design_proposals.jsonl",
        label="tool_design_proposals",
        blockers=blockers,
    )
    forecast_ledger_rows = _read_registry_jsonl(
        registry_path / "report_forecast_ledger.jsonl",
        label="report_forecast_ledger",
        blockers=blockers,
    )
    outcome_label_rows = _read_registry_jsonl(
        registry_path / "report_outcome_labels.jsonl",
        label="report_outcome_labels",
        blockers=blockers,
    )
    outcome_labeling_readiness = _read_registry_json(
        registry_path / "outcome_labeling_readiness.json",
        label="outcome_labeling_readiness",
        blockers=blockers,
    )
    source_performance_profile_rows = _read_registry_jsonl(
        registry_path / "source_performance_profiles.jsonl",
        label="source_performance_profiles",
        blockers=blockers,
    )
    viewpoint_performance_profile_rows = _read_registry_jsonl(
        registry_path / "viewpoint_performance_profiles.jsonl",
        label="viewpoint_performance_profiles",
        blockers=blockers,
    )
    method_performance_profile_rows = _read_registry_jsonl(
        registry_path / "method_performance_profiles.jsonl",
        label="method_performance_profiles",
        blockers=blockers,
    )
    analysis_recipe_rows = _read_registry_jsonl(
        registry_path / "analysis_recipes.jsonl",
        label="analysis_recipes",
        blockers=blockers,
    )
    weighted_research_context_rows = _read_registry_jsonl(
        registry_path / "weighted_research_contexts.jsonl",
        label="weighted_research_contexts",
        blockers=blockers,
    )
    runtime_tool_gap_observation_rows = _read_registry_jsonl(
        registry_path / "runtime_tool_gap_observations.jsonl",
        label="runtime_tool_gap_observations",
        blockers=blockers,
    )
    monitoring_report = _read_registry_json(
        registry_path / "monitoring_report.json",
        label="monitoring_report",
        blockers=blockers,
    )
    runtime_safety_audit = _read_registry_json(
        registry_path / "runtime_safety_audit.json",
        label="runtime_safety_audit",
        blockers=blockers,
    )
    pit_leakage_audit = _read_registry_json(
        registry_path / "pit_leakage_audit.json",
        label="pit_leakage_audit",
        blockers=blockers,
    )
    extraction_provenance_audit = _read_registry_json(
        registry_path / "extraction_provenance_audit.json",
        label="extraction_provenance_audit",
        blockers=blockers,
    )
    statistical_robustness_audit = _read_registry_json(
        registry_path / "statistical_robustness_audit.json",
        label="statistical_robustness_audit",
        blockers=blockers,
    )
    tool_feasibility_audit = _read_registry_json(
        registry_path / "tool_feasibility_audit.json",
        label="tool_feasibility_audit",
        blockers=blockers,
    )
    recipe_validation_audit = _read_registry_json(
        registry_path / "recipe_validation_audit.json",
        label="recipe_validation_audit",
        blockers=blockers,
    )
    footprint_review_summary = _read_registry_json(
        registry_path / "analytical_footprint_review_summary.json",
        label="analytical_footprint_review_summary",
        blockers=blockers,
    )
    footprint_error_taxonomy = _read_registry_json(
        registry_path / "analytical_footprint_error_taxonomy.json",
        label="analytical_footprint_error_taxonomy",
        blockers=blockers,
    )
    gold_review_summary = _read_registry_json(
        registry_path.parent / "gold_sets/tushare_research_reports.review_summary.json",
        label="gold_review_summary",
        blockers=blockers,
    )
    report = build_report_intelligence_patch_v1_5_coverage_report(
        run_id=run_id,
        feature_flags=feature_flags,
        metadata_rows=metadata_rows,
        forecast_rows=forecast_rows,
        footprint_rows=footprint_rows,
        metric_rows=metric_rows,
        method_rows=method_rows,
        tool_coverage_match_rows=tool_coverage_match_rows,
        tool_gap_rows=tool_gap_rows,
        data_acquisition_proposal_rows=data_acquisition_proposal_rows,
        tool_design_proposal_rows=tool_design_proposal_rows,
        forecast_ledger_rows=forecast_ledger_rows,
        outcome_label_rows=outcome_label_rows,
        outcome_labeling_readiness=outcome_labeling_readiness,
        source_performance_profile_rows=source_performance_profile_rows,
        viewpoint_performance_profile_rows=viewpoint_performance_profile_rows,
        method_performance_profile_rows=method_performance_profile_rows,
        analysis_recipe_rows=analysis_recipe_rows,
        weighted_research_context_rows=weighted_research_context_rows,
        runtime_tool_gap_observation_rows=runtime_tool_gap_observation_rows,
        monitoring_report=monitoring_report,
        runtime_safety_audit=runtime_safety_audit,
        pit_leakage_audit=pit_leakage_audit,
        extraction_provenance_audit=extraction_provenance_audit,
        statistical_robustness_audit=statistical_robustness_audit,
        tool_feasibility_audit=tool_feasibility_audit,
        recipe_validation_audit=recipe_validation_audit,
        footprint_review_summary=footprint_review_summary,
        footprint_error_taxonomy=footprint_error_taxonomy,
        gold_review_summary=gold_review_summary,
    )
    if blockers:
        report = dict(report)
        combined_blockers = [
            *[str(item) for item in report.get("blockers", [])],
            *blockers,
        ]
        report["accepted"] = False
        report["blockers"] = combined_blockers
        report["blocker_count"] = len(combined_blockers)
    return _write_json(registry_path / "patch_v1_5_coverage_report.json", report)


def _append_unique_records(
    target: list[dict[str, Any]],
    records: Sequence[dict[str, Any]],
    *,
    key: str,
) -> None:
    seen = {str(record.get(key) or "") for record in target}
    for record in records:
        value = str(record.get(key) or "")
        if value and value not in seen:
            target.append(record)
            seen.add(value)


def _extract_for_markdown(
    row: Mapping[str, Any],
    markdown_text: str,
    *,
    run_id: str,
    extractor: LlmExtractor,
    chunk_chars: int,
    max_chunks: int,
) -> tuple[dict[str, list[dict[str, Any]]], str, str | None, list[str], int, bool]:
    chunks = _chunk_text(markdown_text, chunk_chars=chunk_chars, max_chunks=max_chunks)
    truncated = len("".join(chunks)) < len(markdown_text.strip())
    report_id = _report_id(row)
    all_forecasts: list[dict[str, Any]] = []
    all_footprints: list[dict[str, Any]] = []
    all_metrics: list[dict[str, Any]] = []
    all_methods: list[dict[str, Any]] = []
    all_gaps: list[dict[str, Any]] = []
    blockers: list[str] = []
    model_used: str | None = None
    for index, chunk in enumerate(chunks, 1):
        chunk_span_id = f"{row.get('source_id')}:original_markdown:chunk-{index:03d}"
        try:
            result = extractor(row, chunk, chunk_span_id, index, len(chunks))
        except Exception as exc:  # pragma: no cover - exercised by live failures
            result = {"status": "blocked", "blocker": f"llm_extractor_error: {exc}"}
        if result.get("status") != "ok":
            blockers.append(
                f"{row.get('source_id')} chunk {index}: "
                f"{result.get('blocker') or 'llm_extraction_failed'}"
            )
            if result.get("model"):
                model_used = str(result["model"])
            continue
        model = str(result.get("model") or model_used or "unknown")
        model_used = model
        payload = _ensure_mapping(result.get("payload"))
        footprints = _normalize_footprints(
            payload,
            row,
            run_id=run_id,
            model=model,
            report_id=report_id,
            chunk_span_id=chunk_span_id,
        )
        metrics = _normalize_metric_candidates(
            payload,
            footprints,
            run_id=run_id,
            model=model,
        )
        methods = _normalize_method_patterns(
            payload,
            footprints,
            run_id=run_id,
            model=model,
        )
        gaps = _normalize_tool_gaps(
            payload,
            metrics,
            methods,
            run_id=run_id,
            model=model,
        )
        _append_unique_records(
            all_forecasts,
            _normalize_forecast_claims(
                payload,
                row,
                run_id=run_id,
                model=model,
                report_id=report_id,
                chunk_span_id=chunk_span_id,
            ),
            key="forecast_claim_id",
        )
        _append_unique_records(all_footprints, footprints, key="footprint_id")
        _append_unique_records(all_metrics, metrics, key="metric_candidate_id")
        _append_unique_records(all_methods, methods, key="method_pattern_id")
        _append_unique_records(all_gaps, gaps, key="tool_gap_id")
    llm_status = "processed" if model_used and not blockers else "blocked"
    if not chunks:
        llm_status = "blocked"
        blockers.append(f"{row.get('source_id')}: markdown_empty")
    return (
        {
            "forecast_claims": all_forecasts,
            "analytical_footprints": all_footprints,
            "metric_candidates": all_metrics,
            "method_patterns": all_methods,
            "tool_gaps": all_gaps,
        },
        llm_status,
        model_used,
        blockers,
        len(chunks),
        truncated,
    )


def run_report_intelligence_derived_refresh(
    config: ReportIntelligenceConfig | None = None,
) -> ReportIntelligenceRunResult:
    cfg = config or ReportIntelligenceConfig(refresh_derived_only=True)
    root_path = Path(cfg.root).resolve()
    registry_dir = (
        Path(cfg.registry_dir)
        if Path(cfg.registry_dir).is_absolute()
        else root_path / cfg.registry_dir
    )
    run_id = "RIR-DERIVED-" + _utc_now().replace(":", "").replace("-", "")
    missing_private_inputs = _missing_report_intelligence_private_inputs(
        root_path=root_path,
        registry_dir=registry_dir,
    )
    existing_public_outputs = _report_intelligence_paths_exist(
        root_path=root_path,
        registry_dir=registry_dir,
        paths=REPORT_INTELLIGENCE_PUBLIC_DERIVED_OUTPUT_PATHS,
    )
    if missing_private_inputs and existing_public_outputs:
        blockers = (
            "private report-intelligence inputs missing; refusing to overwrite "
            "committed public derived artifacts: "
            + ", ".join(missing_private_inputs)
        )
        return _blocked_report_intelligence_derived_refresh_result(
            root_path=root_path,
            registry_dir=registry_dir,
            run_id=run_id,
            blockers=(blockers,),
        )
    blockers: list[str] = []
    metadata_rows = _read_registry_jsonl(
        registry_dir / "report_metadata.jsonl",
        label="report_metadata",
        blockers=blockers,
    )
    forecast_rows = _read_registry_jsonl(
        registry_dir / "forecast_claims.jsonl",
        label="forecast_claims",
        blockers=blockers,
    )
    forecast_rows = _refresh_forecast_mapping_governance(forecast_rows)
    footprint_rows = _read_registry_jsonl(
        registry_dir / "analytical_footprints.jsonl",
        label="analytical_footprints",
        blockers=blockers,
    )
    footprint_rows = _refresh_analytical_footprint_indicator_governance(
        footprint_rows
    )
    metric_rows = _read_registry_jsonl(
        registry_dir / "metric_candidates.jsonl",
        label="metric_candidates",
        blockers=blockers,
    )
    method_rows = _read_registry_jsonl(
        registry_dir / "method_patterns.jsonl",
        label="method_patterns",
        blockers=blockers,
    )
    tool_gap_rows = _read_registry_jsonl(
        registry_dir / "tool_gaps.jsonl",
        label="tool_gaps",
        blockers=blockers,
    )
    _append_unique_records(
        metric_rows,
        _normalize_metric_candidates(
            {},
            footprint_rows,
            run_id=run_id,
            model="derived_refresh",
        ),
        key="metric_candidate_id",
    )
    tool_gap_rows = _backfill_tool_gaps_from_metric_candidates(
        tool_gap_rows,
        metric_rows,
        method_rows,
        run_id=run_id,
        model="derived_refresh",
    )
    metric_rows = _backfill_metric_candidates_from_tool_gaps(
        metric_rows,
        tool_gap_rows,
        run_id=run_id,
    )

    forecast_ledger_rows = build_forecast_ledger_records(forecast_rows)
    markdown_coverage_summary = build_markdown_coverage_summary(
        run_id=run_id,
        metadata_rows=metadata_rows,
    )
    industry_etf_proxy_map_rows = _read_industry_etf_proxy_map_rows(registry_dir)
    industry_etf_proxy_pit_availability = build_industry_etf_proxy_pit_availability(
        root_path=root_path,
        qlib_etf_dir=cfg.qlib_etf_dir,
        mapping_rows=industry_etf_proxy_map_rows,
        forecast_rows=forecast_rows,
        metadata_rows=metadata_rows,
    )
    outcome_label_rows = build_outcome_label_records(
        root_path=root_path,
        qlib_etf_dir=cfg.qlib_etf_dir,
        qlib_stock_dir=cfg.qlib_stock_dir,
        forecast_rows=forecast_rows,
        forecast_ledger_rows=forecast_ledger_rows,
        metadata_rows=metadata_rows,
        industry_etf_proxy_map_rows=industry_etf_proxy_map_rows,
        industry_etf_proxy_pit_availability=industry_etf_proxy_pit_availability,
    )
    industry_etf_proxy_readiness = build_industry_etf_proxy_readiness(
        root_path=root_path,
        qlib_etf_dir=cfg.qlib_etf_dir,
        forecast_rows=forecast_rows,
        metadata_rows=metadata_rows,
        mapping_rows=industry_etf_proxy_map_rows,
        pit_availability=industry_etf_proxy_pit_availability,
    )
    stock_price_proxy_readiness = build_stock_price_proxy_readiness(
        root_path=root_path,
        qlib_stock_dir=cfg.qlib_stock_dir,
        qlib_etf_dir=cfg.qlib_etf_dir,
        forecast_rows=forecast_rows,
        metadata_rows=metadata_rows,
    )
    outcome_labeling_readiness = build_outcome_labeling_readiness_report(
        forecast_rows=forecast_rows,
        forecast_ledger_rows=forecast_ledger_rows,
        industry_etf_proxy_readiness=industry_etf_proxy_readiness,
        stock_price_proxy_readiness=stock_price_proxy_readiness,
    )
    source_performance_profile_rows = build_source_performance_profiles(
        metadata_rows,
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_label_rows,
    )
    viewpoint_performance_profile_rows = build_viewpoint_performance_profiles(
        forecast_rows,
        outcome_label_rows=outcome_label_rows,
    )
    method_performance_profile_rows = build_method_performance_profiles(
        method_rows,
        outcome_label_rows=outcome_label_rows,
    )
    tool_coverage_match_rows = build_tool_coverage_matches(metric_rows)
    data_acquisition_proposal_rows = build_data_acquisition_proposals(
        tool_gap_rows,
    )
    tool_design_proposal_rows = build_tool_design_proposals(tool_gap_rows)
    analysis_recipe_rows = build_analysis_recipes(method_rows)
    recipe_paper_trading_run_rows = build_recipe_paper_trading_runs(
        run_id=run_id,
        analysis_recipe_rows=analysis_recipe_rows,
        outcome_label_rows=outcome_label_rows,
        method_performance_profile_rows=method_performance_profile_rows,
    )
    recipe_paper_trading_summary = build_recipe_paper_trading_summary(
        run_id=run_id,
        recipe_paper_trading_runs=recipe_paper_trading_run_rows,
    )
    confidence_impact_observation_rows = build_confidence_impact_observations(
        run_id=run_id,
        recipe_paper_trading_runs=recipe_paper_trading_run_rows,
    )
    confidence_impact_monitor = build_confidence_impact_monitor(
        run_id=run_id,
        confidence_observation_rows=confidence_impact_observation_rows,
        recipe_paper_trading_summary=recipe_paper_trading_summary,
    )
    prompt_mutation_candidate_rows = build_prompt_mutation_candidates(
        run_id=run_id,
        outcome_labeling_readiness=outcome_labeling_readiness,
        tool_gap_rows=tool_gap_rows,
        recipe_paper_trading_runs=recipe_paper_trading_run_rows,
        confidence_impact_observation_rows=confidence_impact_observation_rows,
        confidence_impact_monitor=confidence_impact_monitor,
        markdown_coverage_summary=markdown_coverage_summary,
        industry_etf_proxy_pit_availability=industry_etf_proxy_pit_availability,
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_label_rows,
    )
    weighted_research_context_rows = build_weighted_research_contexts(
        forecast_rows=forecast_rows,
        forecast_ledger_rows=forecast_ledger_rows,
        footprint_rows=footprint_rows,
        analysis_recipe_rows=analysis_recipe_rows,
        tool_gap_rows=tool_gap_rows,
        metadata_rows=metadata_rows,
        source_performance_profile_rows=source_performance_profile_rows,
        viewpoint_performance_profile_rows=viewpoint_performance_profile_rows,
    )
    runtime_tool_gap_observation_rows = build_runtime_tool_gap_observations(
        run_id=run_id,
        weighted_research_context_rows=weighted_research_context_rows,
        tool_gap_rows=tool_gap_rows,
        analysis_recipe_rows=analysis_recipe_rows,
    )
    monitoring_report = build_report_intelligence_monitoring_report(
        run_id=run_id,
        metadata_rows=metadata_rows,
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_label_rows,
        source_performance_profile_rows=source_performance_profile_rows,
        viewpoint_performance_profile_rows=viewpoint_performance_profile_rows,
        method_performance_profile_rows=method_performance_profile_rows,
        tool_coverage_match_rows=tool_coverage_match_rows,
        tool_gap_rows=tool_gap_rows,
        data_acquisition_proposal_rows=data_acquisition_proposal_rows,
        tool_design_proposal_rows=tool_design_proposal_rows,
        analysis_recipe_rows=analysis_recipe_rows,
        weighted_research_context_rows=weighted_research_context_rows,
        runtime_tool_gap_observation_rows=runtime_tool_gap_observation_rows,
        confidence_impact_monitor=confidence_impact_monitor,
    )
    feature_flag_payload = _report_intelligence_feature_flag_payload()
    runtime_safety_audit = build_report_intelligence_runtime_safety_audit(
        run_id=run_id,
        feature_flags=feature_flag_payload,
        forecast_rows=forecast_rows,
        forecast_ledger_rows=forecast_ledger_rows,
        method_rows=method_rows,
        analysis_recipe_rows=analysis_recipe_rows,
        weighted_research_context_rows=weighted_research_context_rows,
        runtime_tool_gap_observation_rows=runtime_tool_gap_observation_rows,
        tool_gap_rows=tool_gap_rows,
    )
    pit_leakage_audit = build_report_intelligence_pit_leakage_audit(
        run_id=run_id,
        feature_flags=feature_flag_payload,
        metadata_rows=metadata_rows,
        forecast_rows=forecast_rows,
        forecast_ledger_rows=forecast_ledger_rows,
        outcome_label_rows=outcome_label_rows,
        source_performance_profile_rows=source_performance_profile_rows,
        tool_coverage_match_rows=tool_coverage_match_rows,
        analysis_recipe_rows=analysis_recipe_rows,
        weighted_research_context_rows=weighted_research_context_rows,
    )
    extraction_provenance_audit = build_report_intelligence_extraction_provenance_audit(
        run_id=run_id,
        forecast_rows=forecast_rows,
        footprint_rows=footprint_rows,
        metric_rows=metric_rows,
        forecast_ledger_rows=forecast_ledger_rows,
        outcome_label_rows=outcome_label_rows,
        outcome_labeling_readiness=outcome_labeling_readiness,
    )
    statistical_robustness_audit = (
        build_report_intelligence_statistical_robustness_audit(
            run_id=run_id,
            feature_flags=feature_flag_payload,
            forecast_ledger_rows=forecast_ledger_rows,
            outcome_label_rows=outcome_label_rows,
            source_performance_profile_rows=source_performance_profile_rows,
            viewpoint_performance_profile_rows=viewpoint_performance_profile_rows,
            method_performance_profile_rows=method_performance_profile_rows,
            weighted_research_context_rows=weighted_research_context_rows,
        )
    )
    tool_feasibility_audit = build_report_intelligence_tool_feasibility_audit(
        run_id=run_id,
        feature_flags=feature_flag_payload,
        metric_rows=metric_rows,
        tool_coverage_match_rows=tool_coverage_match_rows,
        tool_gap_rows=tool_gap_rows,
        data_acquisition_proposal_rows=data_acquisition_proposal_rows,
        tool_design_proposal_rows=tool_design_proposal_rows,
        analysis_recipe_rows=analysis_recipe_rows,
        runtime_tool_gap_observation_rows=runtime_tool_gap_observation_rows,
    )
    recipe_validation_audit = build_report_intelligence_recipe_validation_audit(
        run_id=run_id,
        feature_flags=feature_flag_payload,
        method_rows=method_rows,
        analysis_recipe_rows=analysis_recipe_rows,
        tool_feasibility_audit=tool_feasibility_audit,
        weighted_research_context_rows=weighted_research_context_rows,
        runtime_tool_gap_observation_rows=runtime_tool_gap_observation_rows,
    )
    footprint_review_outputs = write_analytical_footprint_review_artifacts(
        registry_dir,
        footprint_rows,
    )
    footprint_review_load_blockers: list[str] = []
    footprint_review_summary = _read_registry_json(
        registry_dir / "analytical_footprint_review_summary.json",
        label="analytical_footprint_review_summary",
        blockers=footprint_review_load_blockers,
    )
    footprint_error_taxonomy = _read_registry_json(
        registry_dir / "analytical_footprint_error_taxonomy.json",
        label="analytical_footprint_error_taxonomy",
        blockers=footprint_review_load_blockers,
    )
    gold_review_summary = _read_registry_json(
        registry_dir.parent / "gold_sets/tushare_research_reports.review_summary.json",
        label="gold_review_summary",
        blockers=footprint_review_load_blockers,
    )
    patch_v1_5_coverage_report = (
        build_report_intelligence_patch_v1_5_coverage_report(
            run_id=run_id,
            feature_flags=feature_flag_payload,
            metadata_rows=metadata_rows,
            forecast_rows=forecast_rows,
            footprint_rows=footprint_rows,
            metric_rows=metric_rows,
            method_rows=method_rows,
            tool_coverage_match_rows=tool_coverage_match_rows,
            tool_gap_rows=tool_gap_rows,
            data_acquisition_proposal_rows=data_acquisition_proposal_rows,
            tool_design_proposal_rows=tool_design_proposal_rows,
            forecast_ledger_rows=forecast_ledger_rows,
            outcome_label_rows=outcome_label_rows,
            outcome_labeling_readiness=outcome_labeling_readiness,
            source_performance_profile_rows=source_performance_profile_rows,
            viewpoint_performance_profile_rows=viewpoint_performance_profile_rows,
            method_performance_profile_rows=method_performance_profile_rows,
            analysis_recipe_rows=analysis_recipe_rows,
            weighted_research_context_rows=weighted_research_context_rows,
            runtime_tool_gap_observation_rows=runtime_tool_gap_observation_rows,
            monitoring_report=monitoring_report,
            runtime_safety_audit=runtime_safety_audit,
            pit_leakage_audit=pit_leakage_audit,
            extraction_provenance_audit=extraction_provenance_audit,
            statistical_robustness_audit=statistical_robustness_audit,
            tool_feasibility_audit=tool_feasibility_audit,
            recipe_validation_audit=recipe_validation_audit,
            footprint_review_summary=footprint_review_summary,
            footprint_error_taxonomy=footprint_error_taxonomy,
            gold_review_summary=gold_review_summary,
        )
    )
    schema_validation_report = _read_schema_validation_report(root_path)
    evolution_history = _prepare_evolution_refresh_history(
        registry_dir=registry_dir,
        run_id=run_id,
        confidence_impact_monitor=confidence_impact_monitor,
        schema_validation_report=schema_validation_report,
        pit_leakage_audit=pit_leakage_audit,
        extraction_provenance_audit=extraction_provenance_audit,
        statistical_robustness_audit=statistical_robustness_audit,
        outcome_labeling_readiness=outcome_labeling_readiness,
    )
    evolution_readiness_gate = build_report_intelligence_evolution_readiness_gate(
        run_id=run_id,
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_label_rows,
        recipe_paper_trading_summary=recipe_paper_trading_summary,
        confidence_impact_monitor=confidence_impact_monitor,
        markdown_coverage_summary=markdown_coverage_summary,
        pit_leakage_audit=pit_leakage_audit,
        extraction_provenance_audit=extraction_provenance_audit,
        statistical_robustness_audit=statistical_robustness_audit,
        gold_review_summary=gold_review_summary,
        outcome_labeling_readiness=outcome_labeling_readiness,
        schema_validation_report=schema_validation_report,
        monitor_refresh_history_rows=evolution_history["monitor_previous"],
        audit_refresh_history_rows=evolution_history["audit_previous"],
        gap_distribution_history_rows=evolution_history["gap_previous"],
    )
    prompt_mutation_candidate_rows = build_prompt_mutation_candidates(
        run_id=run_id,
        outcome_labeling_readiness=outcome_labeling_readiness,
        tool_gap_rows=tool_gap_rows,
        recipe_paper_trading_runs=recipe_paper_trading_run_rows,
        confidence_impact_observation_rows=confidence_impact_observation_rows,
        confidence_impact_monitor=confidence_impact_monitor,
        markdown_coverage_summary=markdown_coverage_summary,
        industry_etf_proxy_pit_availability=industry_etf_proxy_pit_availability,
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_label_rows,
        evolution_readiness_gate=evolution_readiness_gate,
        gold_review_summary=gold_review_summary,
    )

    outputs = {
        "feature_flags": str(
            _write_json(
                registry_dir / "feature_flags.json",
                feature_flag_payload,
            )["path"]
        ),
        "report_metadata": str(registry_dir / "report_metadata.jsonl"),
        "forecast_claims": str(
            _write_jsonl(registry_dir / "forecast_claims.jsonl", forecast_rows)["path"]
        ),
        "analytical_footprints": str(
            registry_dir / "analytical_footprints.jsonl"
        ),
        **footprint_review_outputs,
        "metric_candidates": str(
            _write_jsonl(registry_dir / "metric_candidates.jsonl", metric_rows)["path"]
        ),
        "method_patterns": str(registry_dir / "method_patterns.jsonl"),
        "tool_gaps": str(
            _write_jsonl(
                registry_dir / "tool_gaps.jsonl",
                tool_gap_rows,
            )["path"]
        ),
        "report_forecast_ledger": str(
            _write_jsonl(
                registry_dir / "report_forecast_ledger.jsonl",
                forecast_ledger_rows,
            )["path"]
        ),
        "markdown_coverage_summary": str(
            _write_json(
                registry_dir / "markdown_coverage_summary.json",
                markdown_coverage_summary,
            )["path"]
        ),
        "industry_etf_proxy_map": str(
            _write_jsonl(
                registry_dir / "industry_etf_proxy_map.jsonl",
                industry_etf_proxy_map_rows,
            )["path"]
        ),
        "industry_etf_proxy_pit_availability": str(
            _write_json(
                registry_dir / "industry_etf_proxy_pit_availability.json",
                industry_etf_proxy_pit_availability,
            )["path"]
        ),
        "outcome_labeling_readiness": str(
            _write_json(
                registry_dir / "outcome_labeling_readiness.json",
                outcome_labeling_readiness,
            )["path"]
        ),
        "report_outcome_labels": str(
            _write_jsonl(
                registry_dir / "report_outcome_labels.jsonl",
                outcome_label_rows,
            )["path"]
        ),
        "source_performance_profiles": str(
            _write_jsonl(
                registry_dir / "source_performance_profiles.jsonl",
                source_performance_profile_rows,
            )["path"]
        ),
        "viewpoint_performance_profiles": str(
            _write_jsonl(
                registry_dir / "viewpoint_performance_profiles.jsonl",
                viewpoint_performance_profile_rows,
            )["path"]
        ),
        "method_performance_profiles": str(
            _write_jsonl(
                registry_dir / "method_performance_profiles.jsonl",
                method_performance_profile_rows,
            )["path"]
        ),
        "tool_coverage_matches": str(
            _write_jsonl(
                registry_dir / "tool_coverage_matches.jsonl",
                tool_coverage_match_rows,
            )["path"]
        ),
        "data_acquisition_proposals": str(
            _write_jsonl(
                registry_dir / "data_acquisition_proposals.jsonl",
                data_acquisition_proposal_rows,
            )["path"]
        ),
        "tool_design_proposals": str(
            _write_jsonl(
                registry_dir / "tool_design_proposals.jsonl",
                tool_design_proposal_rows,
            )["path"]
        ),
        "analysis_recipes": str(
            _write_jsonl(
                registry_dir / "analysis_recipes.jsonl",
                analysis_recipe_rows,
            )["path"]
        ),
        "recipe_paper_trading_runs": str(
            _write_jsonl(
                registry_dir / "recipe_paper_trading_runs.jsonl",
                recipe_paper_trading_run_rows,
            )["path"]
        ),
        "recipe_paper_trading_summary": str(
            _write_json(
                registry_dir / "recipe_paper_trading_summary.json",
                recipe_paper_trading_summary,
            )["path"]
        ),
        "confidence_impact_observations": str(
            _write_jsonl(
                registry_dir / "confidence_impact_observations.jsonl",
                confidence_impact_observation_rows,
            )["path"]
        ),
        "confidence_impact_monitor": str(
            _write_json(
                registry_dir / "confidence_impact_monitor.json",
                confidence_impact_monitor,
            )["path"]
        ),
        "monitor_refresh_history": str(
            _write_jsonl(
                registry_dir / "monitor_refresh_history.jsonl",
                evolution_history["monitor_updated"],
            )["path"]
        ),
        "audit_refresh_history": str(
            _write_jsonl(
                registry_dir / "audit_refresh_history.jsonl",
                evolution_history["audit_updated"],
            )["path"]
        ),
        "gap_distribution_history": str(
            _write_jsonl(
                registry_dir / "gap_distribution_history.jsonl",
                evolution_history["gap_updated"],
            )["path"]
        ),
        "prompt_mutation_candidates": str(
            _write_jsonl(
                registry_dir / "prompt_mutation_candidates.jsonl",
                prompt_mutation_candidate_rows,
            )["path"]
        ),
        "evolution_readiness_gate": str(
            _write_json(
                registry_dir / "evolution_readiness_gate.json",
                evolution_readiness_gate,
            )["path"]
        ),
        "weighted_research_contexts": str(
            _write_jsonl(
                registry_dir / "weighted_research_contexts.jsonl",
                weighted_research_context_rows,
            )["path"]
        ),
        "runtime_tool_gap_observations": str(
            _write_jsonl(
                registry_dir / "runtime_tool_gap_observations.jsonl",
                runtime_tool_gap_observation_rows,
            )["path"]
        ),
        "monitoring_report": str(
            _write_json(
                registry_dir / "monitoring_report.json",
                monitoring_report,
            )["path"]
        ),
        "runtime_safety_audit": str(
            _write_json(
                registry_dir / "runtime_safety_audit.json",
                runtime_safety_audit,
            )["path"]
        ),
        "pit_leakage_audit": str(
            _write_json(
                registry_dir / "pit_leakage_audit.json",
                pit_leakage_audit,
            )["path"]
        ),
        "extraction_provenance_audit": str(
            _write_json(
                registry_dir / "extraction_provenance_audit.json",
                extraction_provenance_audit,
            )["path"]
        ),
        "statistical_robustness_audit": str(
            _write_json(
                registry_dir / "statistical_robustness_audit.json",
                statistical_robustness_audit,
            )["path"]
        ),
        "tool_feasibility_audit": str(
            _write_json(
                registry_dir / "tool_feasibility_audit.json",
                tool_feasibility_audit,
            )["path"]
        ),
        "recipe_validation_audit": str(
            _write_json(
                registry_dir / "recipe_validation_audit.json",
                recipe_validation_audit,
            )["path"]
        ),
        "patch_v1_5_coverage_report": str(
            _write_json(
                registry_dir / "patch_v1_5_coverage_report.json",
                patch_v1_5_coverage_report,
            )["path"]
        ),
        "status": str(registry_dir / "processing_status.jsonl"),
    }
    outputs = {
        key: _relative_or_absolute(Path(path), root_path)
        for key, path in outputs.items()
    }
    summary_path = registry_dir / "extraction_report.json"
    outputs["summary"] = _relative_or_absolute(summary_path, root_path)
    summary = ReportIntelligenceRunResult(
        run_id=run_id,
        root=str(root_path),
        selected_reports=len(metadata_rows),
        metadata_rows=len(metadata_rows),
        forecast_claim_rows=len(forecast_rows),
        analytical_footprint_rows=len(footprint_rows),
        metric_candidate_rows=len(metric_rows),
        method_pattern_rows=len(method_rows),
        tool_gap_rows=len(tool_gap_rows),
        forecast_ledger_rows=len(forecast_ledger_rows),
        outcome_label_rows=len(outcome_label_rows),
        industry_etf_proxy_outcome_label_rows=sum(
            1
            for row in outcome_label_rows
            if row.get("label_type") == "industry_etf_proxy"
        ),
        industry_etf_proxy_eligible_claim_rows=int(
            industry_etf_proxy_readiness["eligible_claim_count"]
        ),
        industry_etf_proxy_labelable_window_rows=int(
            industry_etf_proxy_readiness["labelable_window_count"]
        ),
        industry_etf_proxy_pending_window_rows=int(
            industry_etf_proxy_readiness["pending_future_window_count"]
        ),
        stock_price_proxy_outcome_label_rows=sum(
            1
            for row in outcome_label_rows
            if row.get("label_type") == "stock_price_proxy"
        ),
        stock_price_proxy_eligible_claim_rows=int(
            stock_price_proxy_readiness["eligible_claim_count"]
        ),
        stock_price_proxy_labelable_window_rows=int(
            stock_price_proxy_readiness["labelable_window_count"]
        ),
        stock_price_proxy_pending_window_rows=int(
            stock_price_proxy_readiness["pending_future_window_count"]
        ),
        source_performance_profile_rows=len(source_performance_profile_rows),
        viewpoint_performance_profile_rows=len(viewpoint_performance_profile_rows),
        method_performance_profile_rows=len(method_performance_profile_rows),
        tool_coverage_match_rows=len(tool_coverage_match_rows),
        data_acquisition_proposal_rows=len(data_acquisition_proposal_rows),
        tool_design_proposal_rows=len(tool_design_proposal_rows),
        analysis_recipe_rows=len(analysis_recipe_rows),
        prompt_mutation_candidate_rows=len(prompt_mutation_candidate_rows),
        weighted_research_context_rows=len(weighted_research_context_rows),
        runtime_tool_gap_observation_rows=len(runtime_tool_gap_observation_rows),
        outcome_labeling_ready_count=int(
            outcome_labeling_readiness["ready_for_outcome_labeling_count"]
        ),
        outcome_labeling_blocked_count=int(outcome_labeling_readiness["blocked_count"]),
        pdf_ready_count=sum(
            1
            for row in metadata_rows
            if _ensure_mapping(row.get("pdf")).get("status") in {"cached", "downloaded"}
        ),
        markdown_ready_count=sum(
            1
            for row in metadata_rows
            if _ensure_mapping(row.get("markdown")).get("status")
            in {"cached", "converted", "converted_text_source"}
        ),
        llm_processed_reports=sum(
            1
            for row in metadata_rows
            if _ensure_mapping(row.get("extraction")).get("llm_status") == "processed"
        ),
        blocker_count=len(blockers),
        blockers=tuple(blockers),
        outputs=outputs,
    )
    summary_payload = asdict(summary)
    summary_payload["root"] = "<repo_root>"
    _write_json(summary_path, summary_payload)
    return summary


def run_report_intelligence_refresh(
    config: ReportIntelligenceConfig | None = None,
    *,
    downloader: PdfDownloader | None = None,
    converter: PdfConverter | None = None,
    llm_extractor: LlmExtractor | None = None,
) -> ReportIntelligenceRunResult:
    cfg = config or ReportIntelligenceConfig()
    if cfg.refresh_derived_only:
        return run_report_intelligence_derived_refresh(cfg)
    root_path = Path(cfg.root).resolve()
    registry_dir = (
        Path(cfg.registry_dir)
        if Path(cfg.registry_dir).is_absolute()
        else root_path / cfg.registry_dir
    )
    cache_dir = (
        Path(cfg.cache_dir)
        if Path(cfg.cache_dir).is_absolute()
        else root_path / cfg.cache_dir
    )
    run_id = "RIR-" + _utc_now().replace(":", "").replace("-", "")
    rows, source_blockers = _selected_source_rows(
        root_path,
        source_path=cfg.source_path,
        source_ids=cfg.source_ids,
        limit=cfg.limit,
        min_publish_date=cfg.min_publish_date,
        max_publish_date=cfg.max_publish_date,
        selection_order=cfg.selection_order,
    )
    blockers: list[str] = list(source_blockers)
    downloader = downloader or (
        lambda url, path, overwrite: download_pdf(
            url,
            path,
            overwrite,
            timeout_seconds=cfg.download_timeout_seconds,
        )
    )
    custom_converter = converter is not None
    converter_fn = converter or (
        lambda pdf, out_dir, md, overwrite: convert_pdf_with_mineru(
            pdf,
            out_dir,
            md,
            overwrite,
            command=cfg.mineru_command,
            args_template=cfg.mineru_args_template,
            timeout_seconds=cfg.mineru_timeout_seconds,
            backend=cfg.mineru_backend,
            server_url=cfg.mineru_server_url,
        )
    )
    llm_extractor = llm_extractor or (
        lambda row, chunk, span_id, chunk_index, chunk_count: call_vllm_extractor(
            row,
            chunk,
            span_id,
            chunk_index,
            chunk_count,
            base_url=cfg.vllm_base_url,
            model=cfg.vllm_model,
            timeout_seconds=cfg.vllm_timeout_seconds,
            max_output_tokens=cfg.max_llm_output_tokens,
        )
    )

    metadata_rows: list[dict[str, Any]] = []
    forecast_rows: list[dict[str, Any]] = []
    footprint_rows: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    method_rows: list[dict[str, Any]] = []
    tool_gap_rows: list[dict[str, Any]] = []
    status_rows: list[dict[str, Any]] = []

    prepared_rows: list[dict[str, Any]] = []
    for row in rows:
        source_id = str(row.get("source_id") or "")
        safe_id = _safe_file_id(source_id)
        url = str(row.get("url") or "").strip()
        pdf_path = cache_dir / "pdfs" / f"{safe_id}.pdf"
        markdown_path = cache_dir / "markdown" / f"{safe_id}.md"
        mineru_output_dir = cache_dir / "mineru" / safe_id
        row_blockers: list[str] = []
        pdf_result: Mapping[str, Any] = {"status": "not_attempted"}
        if not url and not markdown_path.exists():
            row_blockers.append(f"{source_id}: report_url_missing")
        if not cfg.skip_download and url:
            pdf_result = downloader(url, pdf_path, cfg.overwrite)
            if pdf_result.get("status") == "blocked":
                row_blockers.append(f"{source_id}: {pdf_result.get('blocker')}")
        elif pdf_path.exists():
            pdf_result = {
                "status": "cached",
                "path": str(pdf_path),
                "bytes": pdf_path.stat().st_size,
                "sha256": _file_sha256(pdf_path),
            }
        prepared_rows.append(
            {
                "row": row,
                "source_id": source_id,
                "pdf_path": pdf_path,
                "markdown_path": markdown_path,
                "mineru_output_dir": mineru_output_dir,
                "pdf_result": pdf_result,
                "markdown_result": {"status": "not_attempted"},
                "row_blockers": row_blockers,
            }
        )

    if not cfg.skip_convert:
        if custom_converter:
            for prepared in prepared_rows:
                markdown_result = converter_fn(
                    prepared["pdf_path"],
                    prepared["mineru_output_dir"],
                    prepared["markdown_path"],
                    cfg.overwrite,
                )
                prepared["markdown_result"] = markdown_result
                if markdown_result.get("status") == "blocked":
                    prepared["row_blockers"].append(
                        f"{prepared['source_id']}: {markdown_result.get('blocker')}"
                    )
        else:
            conversion_tasks = [
                MineruBatchConversionTask(
                    source_id=str(prepared["source_id"]),
                    pdf_path=prepared["pdf_path"],
                    markdown_path=prepared["markdown_path"],
                )
                for prepared in prepared_rows
            ]
            batch_results = convert_pdfs_with_mineru_batch(
                conversion_tasks,
                cache_dir / "mineru_batch" / run_id,
                cfg.overwrite,
                command=cfg.mineru_command,
                backend=cfg.mineru_backend,
                server_url=cfg.mineru_server_url,
                args_template=cfg.mineru_args_template,
                timeout_seconds=cfg.mineru_timeout_seconds,
                batch_size=cfg.mineru_batch_size,
                max_batch_bytes=cfg.mineru_batch_max_bytes,
            )
            for prepared in prepared_rows:
                markdown_result = batch_results.get(
                    str(prepared["source_id"]),
                    {
                        "status": "blocked",
                        "blocker": "mineru_batch_result_missing",
                        "backend": cfg.mineru_backend,
                    },
                )
                prepared["markdown_result"] = markdown_result
                if markdown_result.get("status") == "blocked":
                    prepared["row_blockers"].append(
                        f"{prepared['source_id']}: {markdown_result.get('blocker')}"
                    )
    else:
        for prepared in prepared_rows:
            markdown_path = prepared["markdown_path"]
            if markdown_path.exists():
                prepared["markdown_result"] = {
                    "status": "cached",
                    "path": str(markdown_path),
                    "backend": cfg.mineru_backend,
                    "bytes": markdown_path.stat().st_size,
                    "sha256": _file_sha256(markdown_path),
                }

    for prepared in prepared_rows:
        row = prepared["row"]
        source_id = str(prepared["source_id"])
        markdown_path = prepared["markdown_path"]
        pdf_result = prepared["pdf_result"]
        markdown_result = prepared["markdown_result"]
        row_blockers = prepared["row_blockers"]
        llm_status = "skipped" if cfg.skip_llm else "blocked"
        llm_model: str | None = None
        chunk_count = 0
        truncated_chunks = False
        markdown_result = _annotate_markdown_quality(markdown_result, markdown_path)
        prepared["markdown_result"] = markdown_result
        if not cfg.skip_llm:
            if markdown_path.exists() and markdown_path.stat().st_size > 0:
                quality_gap = _markdown_quality_gap(markdown_result)
                if quality_gap:
                    row_blockers.append(f"{source_id}: {quality_gap}")
                else:
                    extraction, llm_status, llm_model, llm_blockers, chunk_count, truncated_chunks = (
                        _extract_for_markdown(
                            row,
                            markdown_path.read_text(encoding="utf-8", errors="replace"),
                            run_id=run_id,
                            extractor=llm_extractor,
                            chunk_chars=cfg.chunk_chars,
                            max_chunks=cfg.max_chunks,
                        )
                    )
                    row_blockers.extend(llm_blockers)
                    _append_unique_records(
                        forecast_rows,
                        extraction["forecast_claims"],
                        key="forecast_claim_id",
                    )
                    _append_unique_records(
                        footprint_rows,
                        extraction["analytical_footprints"],
                        key="footprint_id",
                    )
                    _append_unique_records(
                        metric_rows,
                        extraction["metric_candidates"],
                        key="metric_candidate_id",
                    )
                    _append_unique_records(
                        method_rows,
                        extraction["method_patterns"],
                        key="method_pattern_id",
                    )
                    _append_unique_records(
                        tool_gap_rows,
                        extraction["tool_gaps"],
                        key="tool_gap_id",
                    )
            else:
                row_blockers.append(f"{source_id}: original_markdown_missing")

        blockers.extend(row_blockers)
        metadata_rows.append(
            _metadata_record(
                row,
                run_id=run_id,
                root_path=root_path,
                pdf_result=pdf_result,
                markdown_result=markdown_result,
                llm_status=llm_status,
                llm_model=llm_model,
                chunk_count=chunk_count,
                truncated_chunks=truncated_chunks,
                blockers=row_blockers,
            )
        )
        status_rows.append(
            {
                "run_id": run_id,
                "source_id": source_id,
                "report_id": _report_id(row),
                "pdf_status": pdf_result.get("status") or "not_attempted",
                "markdown_status": markdown_result.get("status") or "not_attempted",
                "markdown_backend": markdown_result.get("backend")
                or cfg.mineru_backend,
                "markdown_blocker": markdown_result.get("blocker") or "",
                "markdown_returncode": markdown_result.get("returncode"),
                "markdown_timed_out": bool(markdown_result.get("timed_out")),
                "markdown_duration_seconds": markdown_result.get("duration_seconds"),
                "markdown_quality_gate_status": markdown_result.get(
                    "quality_gate_status"
                )
                or "",
                "markdown_quality_gap": markdown_result.get("quality_gap") or "",
                "markdown_stderr_tail": _redact_runtime_text(
                    markdown_result.get("stderr_tail"),
                    root_path,
                ),
                "markdown_stdout_tail": _redact_runtime_text(
                    markdown_result.get("stdout_tail"),
                    root_path,
                ),
                "llm_status": llm_status,
                "llm_model": llm_model or "",
                "blockers": row_blockers,
            }
        )

    forecast_rows = _refresh_forecast_mapping_governance(forecast_rows)
    footprint_rows = _refresh_analytical_footprint_indicator_governance(
        footprint_rows
    )
    tool_gap_rows = _backfill_tool_gaps_from_metric_candidates(
        tool_gap_rows,
        metric_rows,
        method_rows,
        run_id=run_id,
        model="report_intelligence_refresh",
    )
    metric_rows = _backfill_metric_candidates_from_tool_gaps(
        metric_rows,
        tool_gap_rows,
        run_id=run_id,
    )
    forecast_ledger_rows = build_forecast_ledger_records(forecast_rows)
    markdown_coverage_summary = build_markdown_coverage_summary(
        run_id=run_id,
        metadata_rows=metadata_rows,
    )
    industry_etf_proxy_map_rows = _read_industry_etf_proxy_map_rows(registry_dir)
    industry_etf_proxy_pit_availability = build_industry_etf_proxy_pit_availability(
        root_path=root_path,
        qlib_etf_dir=cfg.qlib_etf_dir,
        mapping_rows=industry_etf_proxy_map_rows,
        forecast_rows=forecast_rows,
        metadata_rows=metadata_rows,
    )
    outcome_label_rows = build_outcome_label_records(
        root_path=root_path,
        qlib_etf_dir=cfg.qlib_etf_dir,
        qlib_stock_dir=cfg.qlib_stock_dir,
        forecast_rows=forecast_rows,
        forecast_ledger_rows=forecast_ledger_rows,
        metadata_rows=metadata_rows,
        industry_etf_proxy_map_rows=industry_etf_proxy_map_rows,
        industry_etf_proxy_pit_availability=industry_etf_proxy_pit_availability,
    )
    industry_etf_proxy_readiness = build_industry_etf_proxy_readiness(
        root_path=root_path,
        qlib_etf_dir=cfg.qlib_etf_dir,
        forecast_rows=forecast_rows,
        metadata_rows=metadata_rows,
        mapping_rows=industry_etf_proxy_map_rows,
        pit_availability=industry_etf_proxy_pit_availability,
    )
    stock_price_proxy_readiness = build_stock_price_proxy_readiness(
        root_path=root_path,
        qlib_stock_dir=cfg.qlib_stock_dir,
        qlib_etf_dir=cfg.qlib_etf_dir,
        forecast_rows=forecast_rows,
        metadata_rows=metadata_rows,
    )
    outcome_labeling_readiness = build_outcome_labeling_readiness_report(
        forecast_rows=forecast_rows,
        forecast_ledger_rows=forecast_ledger_rows,
        industry_etf_proxy_readiness=industry_etf_proxy_readiness,
        stock_price_proxy_readiness=stock_price_proxy_readiness,
    )
    source_performance_profile_rows = build_source_performance_profiles(
        metadata_rows,
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_label_rows,
    )
    viewpoint_performance_profile_rows = build_viewpoint_performance_profiles(
        forecast_rows,
        outcome_label_rows=outcome_label_rows,
    )
    method_performance_profile_rows = build_method_performance_profiles(
        method_rows,
        outcome_label_rows=outcome_label_rows,
    )
    tool_coverage_match_rows = build_tool_coverage_matches(metric_rows)
    data_acquisition_proposal_rows = build_data_acquisition_proposals(
        tool_gap_rows,
    )
    tool_design_proposal_rows = build_tool_design_proposals(tool_gap_rows)
    analysis_recipe_rows = build_analysis_recipes(method_rows)
    recipe_paper_trading_run_rows = build_recipe_paper_trading_runs(
        run_id=run_id,
        analysis_recipe_rows=analysis_recipe_rows,
        outcome_label_rows=outcome_label_rows,
        method_performance_profile_rows=method_performance_profile_rows,
    )
    recipe_paper_trading_summary = build_recipe_paper_trading_summary(
        run_id=run_id,
        recipe_paper_trading_runs=recipe_paper_trading_run_rows,
    )
    confidence_impact_observation_rows = build_confidence_impact_observations(
        run_id=run_id,
        recipe_paper_trading_runs=recipe_paper_trading_run_rows,
    )
    confidence_impact_monitor = build_confidence_impact_monitor(
        run_id=run_id,
        confidence_observation_rows=confidence_impact_observation_rows,
        recipe_paper_trading_summary=recipe_paper_trading_summary,
    )
    prompt_mutation_candidate_rows = build_prompt_mutation_candidates(
        run_id=run_id,
        outcome_labeling_readiness=outcome_labeling_readiness,
        tool_gap_rows=tool_gap_rows,
        recipe_paper_trading_runs=recipe_paper_trading_run_rows,
        confidence_impact_observation_rows=confidence_impact_observation_rows,
        confidence_impact_monitor=confidence_impact_monitor,
        markdown_coverage_summary=markdown_coverage_summary,
        industry_etf_proxy_pit_availability=industry_etf_proxy_pit_availability,
    )
    weighted_research_context_rows = build_weighted_research_contexts(
        forecast_rows=forecast_rows,
        forecast_ledger_rows=forecast_ledger_rows,
        footprint_rows=footprint_rows,
        analysis_recipe_rows=analysis_recipe_rows,
        tool_gap_rows=tool_gap_rows,
        metadata_rows=metadata_rows,
        source_performance_profile_rows=source_performance_profile_rows,
        viewpoint_performance_profile_rows=viewpoint_performance_profile_rows,
    )
    runtime_tool_gap_observation_rows = build_runtime_tool_gap_observations(
        run_id=run_id,
        weighted_research_context_rows=weighted_research_context_rows,
        tool_gap_rows=tool_gap_rows,
        analysis_recipe_rows=analysis_recipe_rows,
    )
    monitoring_report = build_report_intelligence_monitoring_report(
        run_id=run_id,
        metadata_rows=metadata_rows,
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_label_rows,
        source_performance_profile_rows=source_performance_profile_rows,
        viewpoint_performance_profile_rows=viewpoint_performance_profile_rows,
        method_performance_profile_rows=method_performance_profile_rows,
        tool_coverage_match_rows=tool_coverage_match_rows,
        tool_gap_rows=tool_gap_rows,
        data_acquisition_proposal_rows=data_acquisition_proposal_rows,
        tool_design_proposal_rows=tool_design_proposal_rows,
        analysis_recipe_rows=analysis_recipe_rows,
        weighted_research_context_rows=weighted_research_context_rows,
        runtime_tool_gap_observation_rows=runtime_tool_gap_observation_rows,
        confidence_impact_monitor=confidence_impact_monitor,
    )
    feature_flag_payload = _report_intelligence_feature_flag_payload()
    runtime_safety_audit = build_report_intelligence_runtime_safety_audit(
        run_id=run_id,
        feature_flags=feature_flag_payload,
        forecast_rows=forecast_rows,
        forecast_ledger_rows=forecast_ledger_rows,
        method_rows=method_rows,
        analysis_recipe_rows=analysis_recipe_rows,
        weighted_research_context_rows=weighted_research_context_rows,
        runtime_tool_gap_observation_rows=runtime_tool_gap_observation_rows,
        tool_gap_rows=tool_gap_rows,
    )
    pit_leakage_audit = build_report_intelligence_pit_leakage_audit(
        run_id=run_id,
        feature_flags=feature_flag_payload,
        metadata_rows=metadata_rows,
        forecast_rows=forecast_rows,
        forecast_ledger_rows=forecast_ledger_rows,
        outcome_label_rows=outcome_label_rows,
        source_performance_profile_rows=source_performance_profile_rows,
        tool_coverage_match_rows=tool_coverage_match_rows,
        analysis_recipe_rows=analysis_recipe_rows,
        weighted_research_context_rows=weighted_research_context_rows,
    )
    extraction_provenance_audit = build_report_intelligence_extraction_provenance_audit(
        run_id=run_id,
        forecast_rows=forecast_rows,
        footprint_rows=footprint_rows,
        metric_rows=metric_rows,
        forecast_ledger_rows=forecast_ledger_rows,
        outcome_label_rows=outcome_label_rows,
        outcome_labeling_readiness=outcome_labeling_readiness,
    )
    statistical_robustness_audit = (
        build_report_intelligence_statistical_robustness_audit(
            run_id=run_id,
            feature_flags=feature_flag_payload,
            forecast_ledger_rows=forecast_ledger_rows,
            outcome_label_rows=outcome_label_rows,
            source_performance_profile_rows=source_performance_profile_rows,
            viewpoint_performance_profile_rows=viewpoint_performance_profile_rows,
            method_performance_profile_rows=method_performance_profile_rows,
            weighted_research_context_rows=weighted_research_context_rows,
        )
    )
    tool_feasibility_audit = build_report_intelligence_tool_feasibility_audit(
        run_id=run_id,
        feature_flags=feature_flag_payload,
        metric_rows=metric_rows,
        tool_coverage_match_rows=tool_coverage_match_rows,
        tool_gap_rows=tool_gap_rows,
        data_acquisition_proposal_rows=data_acquisition_proposal_rows,
        tool_design_proposal_rows=tool_design_proposal_rows,
        analysis_recipe_rows=analysis_recipe_rows,
        runtime_tool_gap_observation_rows=runtime_tool_gap_observation_rows,
    )
    recipe_validation_audit = build_report_intelligence_recipe_validation_audit(
        run_id=run_id,
        feature_flags=feature_flag_payload,
        method_rows=method_rows,
        analysis_recipe_rows=analysis_recipe_rows,
        tool_feasibility_audit=tool_feasibility_audit,
        weighted_research_context_rows=weighted_research_context_rows,
        runtime_tool_gap_observation_rows=runtime_tool_gap_observation_rows,
    )
    footprint_review_outputs = write_analytical_footprint_review_artifacts(
        registry_dir,
        footprint_rows,
    )
    footprint_review_load_blockers: list[str] = []
    footprint_review_summary = _read_registry_json(
        registry_dir / "analytical_footprint_review_summary.json",
        label="analytical_footprint_review_summary",
        blockers=footprint_review_load_blockers,
    )
    footprint_error_taxonomy = _read_registry_json(
        registry_dir / "analytical_footprint_error_taxonomy.json",
        label="analytical_footprint_error_taxonomy",
        blockers=footprint_review_load_blockers,
    )
    gold_review_summary = _read_registry_json(
        registry_dir.parent / "gold_sets/tushare_research_reports.review_summary.json",
        label="gold_review_summary",
        blockers=footprint_review_load_blockers,
    )
    patch_v1_5_coverage_report = (
        build_report_intelligence_patch_v1_5_coverage_report(
            run_id=run_id,
            feature_flags=feature_flag_payload,
            metadata_rows=metadata_rows,
            forecast_rows=forecast_rows,
            footprint_rows=footprint_rows,
            metric_rows=metric_rows,
            method_rows=method_rows,
            tool_coverage_match_rows=tool_coverage_match_rows,
            tool_gap_rows=tool_gap_rows,
            data_acquisition_proposal_rows=data_acquisition_proposal_rows,
            tool_design_proposal_rows=tool_design_proposal_rows,
            forecast_ledger_rows=forecast_ledger_rows,
            outcome_label_rows=outcome_label_rows,
            outcome_labeling_readiness=outcome_labeling_readiness,
            source_performance_profile_rows=source_performance_profile_rows,
            viewpoint_performance_profile_rows=viewpoint_performance_profile_rows,
            method_performance_profile_rows=method_performance_profile_rows,
            analysis_recipe_rows=analysis_recipe_rows,
            weighted_research_context_rows=weighted_research_context_rows,
            runtime_tool_gap_observation_rows=runtime_tool_gap_observation_rows,
            monitoring_report=monitoring_report,
            runtime_safety_audit=runtime_safety_audit,
            pit_leakage_audit=pit_leakage_audit,
            extraction_provenance_audit=extraction_provenance_audit,
            statistical_robustness_audit=statistical_robustness_audit,
            tool_feasibility_audit=tool_feasibility_audit,
            recipe_validation_audit=recipe_validation_audit,
            footprint_review_summary=footprint_review_summary,
            footprint_error_taxonomy=footprint_error_taxonomy,
            gold_review_summary=gold_review_summary,
        )
    )
    schema_validation_report = _read_schema_validation_report(root_path)
    evolution_history = _prepare_evolution_refresh_history(
        registry_dir=registry_dir,
        run_id=run_id,
        confidence_impact_monitor=confidence_impact_monitor,
        schema_validation_report=schema_validation_report,
        pit_leakage_audit=pit_leakage_audit,
        extraction_provenance_audit=extraction_provenance_audit,
        statistical_robustness_audit=statistical_robustness_audit,
        outcome_labeling_readiness=outcome_labeling_readiness,
    )
    evolution_readiness_gate = build_report_intelligence_evolution_readiness_gate(
        run_id=run_id,
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_label_rows,
        recipe_paper_trading_summary=recipe_paper_trading_summary,
        confidence_impact_monitor=confidence_impact_monitor,
        markdown_coverage_summary=markdown_coverage_summary,
        pit_leakage_audit=pit_leakage_audit,
        extraction_provenance_audit=extraction_provenance_audit,
        statistical_robustness_audit=statistical_robustness_audit,
        gold_review_summary=gold_review_summary,
        outcome_labeling_readiness=outcome_labeling_readiness,
        schema_validation_report=schema_validation_report,
        monitor_refresh_history_rows=evolution_history["monitor_previous"],
        audit_refresh_history_rows=evolution_history["audit_previous"],
        gap_distribution_history_rows=evolution_history["gap_previous"],
    )
    prompt_mutation_candidate_rows = build_prompt_mutation_candidates(
        run_id=run_id,
        outcome_labeling_readiness=outcome_labeling_readiness,
        tool_gap_rows=tool_gap_rows,
        recipe_paper_trading_runs=recipe_paper_trading_run_rows,
        confidence_impact_observation_rows=confidence_impact_observation_rows,
        confidence_impact_monitor=confidence_impact_monitor,
        markdown_coverage_summary=markdown_coverage_summary,
        industry_etf_proxy_pit_availability=industry_etf_proxy_pit_availability,
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_label_rows,
        evolution_readiness_gate=evolution_readiness_gate,
        gold_review_summary=gold_review_summary,
    )

    outputs = {
        "feature_flags": str(
            _write_json(
                registry_dir / "feature_flags.json",
                feature_flag_payload,
            )["path"]
        ),
        "report_metadata": str(
            _write_jsonl(registry_dir / "report_metadata.jsonl", metadata_rows)["path"]
        ),
        "forecast_claims": str(
            _write_jsonl(registry_dir / "forecast_claims.jsonl", forecast_rows)["path"]
        ),
        "analytical_footprints": str(
            _write_jsonl(
                registry_dir / "analytical_footprints.jsonl",
                footprint_rows,
            )["path"]
        ),
        **footprint_review_outputs,
        "metric_candidates": str(
            _write_jsonl(registry_dir / "metric_candidates.jsonl", metric_rows)["path"]
        ),
        "method_patterns": str(
            _write_jsonl(registry_dir / "method_patterns.jsonl", method_rows)["path"]
        ),
        "tool_gaps": str(
            _write_jsonl(registry_dir / "tool_gaps.jsonl", tool_gap_rows)["path"]
        ),
        "report_forecast_ledger": str(
            _write_jsonl(
                registry_dir / "report_forecast_ledger.jsonl",
                forecast_ledger_rows,
            )["path"]
        ),
        "markdown_coverage_summary": str(
            _write_json(
                registry_dir / "markdown_coverage_summary.json",
                markdown_coverage_summary,
            )["path"]
        ),
        "industry_etf_proxy_map": str(
            _write_jsonl(
                registry_dir / "industry_etf_proxy_map.jsonl",
                industry_etf_proxy_map_rows,
            )["path"]
        ),
        "industry_etf_proxy_pit_availability": str(
            _write_json(
                registry_dir / "industry_etf_proxy_pit_availability.json",
                industry_etf_proxy_pit_availability,
            )["path"]
        ),
        "outcome_labeling_readiness": str(
            _write_json(
                registry_dir / "outcome_labeling_readiness.json",
                outcome_labeling_readiness,
            )["path"]
        ),
        "report_outcome_labels": str(
            _write_jsonl(
                registry_dir / "report_outcome_labels.jsonl",
                outcome_label_rows,
            )["path"]
        ),
        "source_performance_profiles": str(
            _write_jsonl(
                registry_dir / "source_performance_profiles.jsonl",
                source_performance_profile_rows,
            )["path"]
        ),
        "viewpoint_performance_profiles": str(
            _write_jsonl(
                registry_dir / "viewpoint_performance_profiles.jsonl",
                viewpoint_performance_profile_rows,
            )["path"]
        ),
        "method_performance_profiles": str(
            _write_jsonl(
                registry_dir / "method_performance_profiles.jsonl",
                method_performance_profile_rows,
            )["path"]
        ),
        "tool_coverage_matches": str(
            _write_jsonl(
                registry_dir / "tool_coverage_matches.jsonl",
                tool_coverage_match_rows,
            )["path"]
        ),
        "data_acquisition_proposals": str(
            _write_jsonl(
                registry_dir / "data_acquisition_proposals.jsonl",
                data_acquisition_proposal_rows,
            )["path"]
        ),
        "tool_design_proposals": str(
            _write_jsonl(
                registry_dir / "tool_design_proposals.jsonl",
                tool_design_proposal_rows,
            )["path"]
        ),
        "analysis_recipes": str(
            _write_jsonl(
                registry_dir / "analysis_recipes.jsonl",
                analysis_recipe_rows,
            )["path"]
        ),
        "recipe_paper_trading_runs": str(
            _write_jsonl(
                registry_dir / "recipe_paper_trading_runs.jsonl",
                recipe_paper_trading_run_rows,
            )["path"]
        ),
        "recipe_paper_trading_summary": str(
            _write_json(
                registry_dir / "recipe_paper_trading_summary.json",
                recipe_paper_trading_summary,
            )["path"]
        ),
        "confidence_impact_observations": str(
            _write_jsonl(
                registry_dir / "confidence_impact_observations.jsonl",
                confidence_impact_observation_rows,
            )["path"]
        ),
        "confidence_impact_monitor": str(
            _write_json(
                registry_dir / "confidence_impact_monitor.json",
                confidence_impact_monitor,
            )["path"]
        ),
        "monitor_refresh_history": str(
            _write_jsonl(
                registry_dir / "monitor_refresh_history.jsonl",
                evolution_history["monitor_updated"],
            )["path"]
        ),
        "audit_refresh_history": str(
            _write_jsonl(
                registry_dir / "audit_refresh_history.jsonl",
                evolution_history["audit_updated"],
            )["path"]
        ),
        "gap_distribution_history": str(
            _write_jsonl(
                registry_dir / "gap_distribution_history.jsonl",
                evolution_history["gap_updated"],
            )["path"]
        ),
        "prompt_mutation_candidates": str(
            _write_jsonl(
                registry_dir / "prompt_mutation_candidates.jsonl",
                prompt_mutation_candidate_rows,
            )["path"]
        ),
        "evolution_readiness_gate": str(
            _write_json(
                registry_dir / "evolution_readiness_gate.json",
                evolution_readiness_gate,
            )["path"]
        ),
        "weighted_research_contexts": str(
            _write_jsonl(
                registry_dir / "weighted_research_contexts.jsonl",
                weighted_research_context_rows,
            )["path"]
        ),
        "runtime_tool_gap_observations": str(
            _write_jsonl(
                registry_dir / "runtime_tool_gap_observations.jsonl",
                runtime_tool_gap_observation_rows,
            )["path"]
        ),
        "monitoring_report": str(
            _write_json(
                registry_dir / "monitoring_report.json",
                monitoring_report,
            )["path"]
        ),
        "runtime_safety_audit": str(
            _write_json(
                registry_dir / "runtime_safety_audit.json",
                runtime_safety_audit,
            )["path"]
        ),
        "pit_leakage_audit": str(
            _write_json(
                registry_dir / "pit_leakage_audit.json",
                pit_leakage_audit,
            )["path"]
        ),
        "extraction_provenance_audit": str(
            _write_json(
                registry_dir / "extraction_provenance_audit.json",
                extraction_provenance_audit,
            )["path"]
        ),
        "statistical_robustness_audit": str(
            _write_json(
                registry_dir / "statistical_robustness_audit.json",
                statistical_robustness_audit,
            )["path"]
        ),
        "tool_feasibility_audit": str(
            _write_json(
                registry_dir / "tool_feasibility_audit.json",
                tool_feasibility_audit,
            )["path"]
        ),
        "recipe_validation_audit": str(
            _write_json(
                registry_dir / "recipe_validation_audit.json",
                recipe_validation_audit,
            )["path"]
        ),
        "patch_v1_5_coverage_report": str(
            _write_json(
                registry_dir / "patch_v1_5_coverage_report.json",
                patch_v1_5_coverage_report,
            )["path"]
        ),
        "status": str(
            _write_jsonl(registry_dir / "processing_status.jsonl", status_rows)["path"]
        ),
    }
    outputs = {
        key: _relative_or_absolute(Path(path), root_path)
        for key, path in outputs.items()
    }
    summary_path = registry_dir / "extraction_report.json"
    outputs["summary"] = _relative_or_absolute(summary_path, root_path)
    summary = ReportIntelligenceRunResult(
        run_id=run_id,
        root=str(root_path),
        selected_reports=len(rows),
        metadata_rows=len(metadata_rows),
        forecast_claim_rows=len(forecast_rows),
        analytical_footprint_rows=len(footprint_rows),
        metric_candidate_rows=len(metric_rows),
        method_pattern_rows=len(method_rows),
        tool_gap_rows=len(tool_gap_rows),
        forecast_ledger_rows=len(forecast_ledger_rows),
        outcome_label_rows=len(outcome_label_rows),
        industry_etf_proxy_outcome_label_rows=sum(
            1
            for row in outcome_label_rows
            if row.get("label_type") == "industry_etf_proxy"
        ),
        industry_etf_proxy_eligible_claim_rows=int(
            industry_etf_proxy_readiness["eligible_claim_count"]
        ),
        industry_etf_proxy_labelable_window_rows=int(
            industry_etf_proxy_readiness["labelable_window_count"]
        ),
        industry_etf_proxy_pending_window_rows=int(
            industry_etf_proxy_readiness["pending_future_window_count"]
        ),
        stock_price_proxy_outcome_label_rows=sum(
            1
            for row in outcome_label_rows
            if row.get("label_type") == "stock_price_proxy"
        ),
        stock_price_proxy_eligible_claim_rows=int(
            stock_price_proxy_readiness["eligible_claim_count"]
        ),
        stock_price_proxy_labelable_window_rows=int(
            stock_price_proxy_readiness["labelable_window_count"]
        ),
        stock_price_proxy_pending_window_rows=int(
            stock_price_proxy_readiness["pending_future_window_count"]
        ),
        source_performance_profile_rows=len(source_performance_profile_rows),
        viewpoint_performance_profile_rows=len(viewpoint_performance_profile_rows),
        method_performance_profile_rows=len(method_performance_profile_rows),
        tool_coverage_match_rows=len(tool_coverage_match_rows),
        data_acquisition_proposal_rows=len(data_acquisition_proposal_rows),
        tool_design_proposal_rows=len(tool_design_proposal_rows),
        analysis_recipe_rows=len(analysis_recipe_rows),
        prompt_mutation_candidate_rows=len(prompt_mutation_candidate_rows),
        weighted_research_context_rows=len(weighted_research_context_rows),
        runtime_tool_gap_observation_rows=len(runtime_tool_gap_observation_rows),
        outcome_labeling_ready_count=int(
            outcome_labeling_readiness["ready_for_outcome_labeling_count"]
        ),
        outcome_labeling_blocked_count=int(outcome_labeling_readiness["blocked_count"]),
        pdf_ready_count=sum(
            1
            for row in metadata_rows
            if row["pdf"]["status"] in {"cached", "downloaded"}
        ),
        markdown_ready_count=sum(
            1
            for row in metadata_rows
            if row["markdown"]["status"] in {"cached", "converted", "converted_text_source"}
        ),
        llm_processed_reports=sum(
            1
            for row in metadata_rows
            if row["extraction"]["llm_status"] == "processed"
        ),
        blocker_count=len(blockers),
        blockers=tuple(blockers),
        outputs=outputs,
    )
    summary_payload = asdict(summary)
    summary_payload["root"] = "<repo_root>"
    _write_json(summary_path, summary_payload)
    return summary
