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
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Sequence

from .manual_review_import import manual_review_forbidden_field_paths
from .phase_minus1 import load_jsonl_with_errors
from .required_data import (
    canonical_metric_name as _canonical_metric_name,
    normalize_required_data_items,
)


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
ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH = (
    "registry/report_intelligence/analytical_footprint_reviewed.jsonl"
)
ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH = (
    "registry/report_intelligence/analytical_footprint_review_batch.jsonl"
)
ANALYTICAL_FOOTPRINT_REVIEW_ASSIST_JSONL_PATH = (
    "registry/report_intelligence/analytical_footprint_review_assist.jsonl"
)
ANALYTICAL_FOOTPRINT_REVIEW_WORKBOOK_MD_PATH = (
    "registry/report_intelligence/analytical_footprint_review_workbook.md"
)
ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_JSONL_PATH = (
    "registry/report_intelligence/analytical_footprint_review_evidence.jsonl"
)
ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_MD_PATH = (
    "registry/report_intelligence/analytical_footprint_review_evidence.md"
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
        ANALYTICAL_FOOTPRINT_REVIEW_ASSIST_JSONL_PATH,
        ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_JSONL_PATH,
        ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_MD_PATH,
        ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
        ANALYTICAL_FOOTPRINT_REVIEW_WORKBOOK_MD_PATH,
        ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
        ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH,
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
REPORT_INTELLIGENCE_NONEMPTY_PRIVATE_DERIVED_INPUT_PATHS = frozenset(
    {
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
DEFAULT_VLLM_TIMEOUT_SECONDS = 7200
DEFAULT_Q_LIB_ETF_PATH = "~/.qlib/qlib_data/cn_etf"
DEFAULT_Q_LIB_STOCK_PATH = "~/.qlib/qlib_data/cn_data"
DEFAULT_MINERU_BACKEND = "hybrid-auto-engine"
DEFAULT_MINERU_ARGS_TEMPLATE = "-p {pdf} -o {output_dir} -b {backend} -m auto"
DEFAULT_MINERU_ENV = {
    "MINERU_TABLE_ENABLE": "true",
    "MINERU_FORMULA_ENABLE": "true",
}
FORECAST_CLAIM_RISK_WARNING_PREFIX_RE = re.compile(
    r"^\s*(?:风险提示|风险因素|风险声明|免责声明)\s*[:：]"
)
GENERIC_RISK_WARNING_ENUM_RE = re.compile(
    r"^\s*(?:\d+[、.)）]|[（(]\d+[）)]|[一二三四五六七八九十]+[、.)）])?\s*"
    r".{0,24}(?:不及预期|低于预期|超预期变化|大盘系统性风险|业绩不达预期|数据误差|竞争加剧|客户依赖|政策落地)"
    r"(?:.*风险)?\s*[。；;]?\s*$"
)
FORECAST_CLAIM_MECHANISM_TERMS = (
    "预计",
    "预期",
    "有望",
    "未来",
    "后续",
    "长期",
    "短期",
    "中期",
    "看好",
    "维持",
    "建议",
    "上调",
    "下调",
    "优于",
    "跑赢",
    "跑输",
    "超配",
    "低配",
    "增持",
    "减持",
    "驱动",
    "推动",
    "带动",
    "导致",
    "受益",
    "压制",
    "制约",
    "改善",
    "修复",
    "恶化",
    "承压",
    "风险",
    "压力",
    "催化",
    "拐点",
    "弹性",
    "传导",
    "供需",
    "库存",
    "产能",
    "景气",
    "景气周期",
    "行业周期",
    "价格周期",
    "煤价周期",
    "格局",
    "regime",
    "outperform",
    "underperform",
)
FORECAST_CLAIM_DESCRIPTIVE_ONLY_TERMS = (
    "涨跌幅",
    "区间涨幅",
    "区间跌幅",
    "年初至",
    "当前",
    "截至",
    "分别为",
    "最高",
    "其次",
    "排在",
    "排名",
    "环比",
    "同比",
    "ROE",
    "毛利率",
    "净利率",
    "资产负债率",
    "研发比例",
    "存量规模",
    "价格为",
    "涨跌不一",
    "规模",
)
FORECAST_CLAIM_FINANCE_IMPACT_TERMS = (
    "需求增长",
    "订单",
    "销量",
    "出货",
    "装机",
    "营收",
    "营业收入",
    "收入增长",
    "利润",
    "盈利",
    "业绩",
    "净利润",
    "毛利率",
    "净利率",
    "估值修复",
    "估值溢价",
    "估值提升",
    "估值重估",
    "价值重估",
    "目标价",
    "股价",
    "股票",
    "指数",
    "行业指数",
    "市场指数",
    "沪深300",
    "高beta",
    "高 beta",
    "风格",
    "收益率",
    "超额收益",
    "相对收益",
    "跑赢",
    "跑输",
    "优于",
    "占优",
    "评级",
    "看多",
    "看空",
    "看好",
    "买入",
    "增持",
    "减持",
    "超配",
    "低配",
    "景气",
    "景气度",
    "景气周期",
    "行业周期",
    "价格周期",
    "煤价周期",
    "价格中枢",
    "流动性",
    "信用扩张",
    "信用收缩",
    "信用利差",
    "信用风险",
    "信用周期",
    "信贷",
    "社融",
    "revenue",
    "profit",
    "earnings",
    "margin",
    "valuation",
    "return",
    "outperform",
    "underperform",
)
MINERU_VLM_HF_CACHE_DIRNAME = "models--opendatalab--MinerU2.5-Pro-2605-1.2B"
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
    "resolved",
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
FORECAST_GOLD_MIN_REVIEWED_CLAIMS = 500
FORECAST_GOLD_MIN_DOCUMENTS = 50
FORECAST_GOLD_REVIEW_MIN_METRICS: Mapping[str, float] = {
    "claim_precision": 0.85,
    "source_span_support_precision": 0.90,
    "target_accuracy": 0.85,
    "direction_accuracy": 0.85,
    "horizon_accuracy": 0.85,
    "variable_mapping_accuracy": 0.80,
}
FORECAST_GOLD_REVIEW_MAX_METRICS: Mapping[str, float] = {
    "unsupported_field_false_grounding_rate": 0.05,
}
MAX_STORED_CLAIM_TEXT_CHARS = 512
MAX_REASONABLE_FORECAST_HORIZON_DAYS = 3653
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
    "工业金属": {"etf_symbol": "SH560860", "mapping_label": "工业有色ETF"},
    "有色金属": {"etf_symbol": "SH512400", "mapping_label": "有色ETF"},
    "贵金属": {"etf_symbol": "SH512400", "mapping_label": "有色ETF"},
    "银行": {"etf_symbol": "SH512800", "mapping_label": "银行ETF"},
    "银行Ⅱ": {"etf_symbol": "SH512800", "mapping_label": "银行ETF"},
    "证券": {"etf_symbol": "SH512880", "mapping_label": "证券ETF"},
    "证券Ⅱ": {"etf_symbol": "SH512880", "mapping_label": "证券ETF"},
    "多元金融": {"etf_symbol": "SH512880", "mapping_label": "证券ETF"},
    "保险": {"etf_symbol": "SH512070", "mapping_label": "证券保险ETF"},
    "半导体": {"etf_symbol": "SH512480", "mapping_label": "半导体ETF"},
    "通信设备": {"etf_symbol": "SH515880", "mapping_label": "通信ETF"},
    "IT服务Ⅱ": {"etf_symbol": "SH515230", "mapping_label": "软件ETF"},
    "计算机设备": {"etf_symbol": "SH512720", "mapping_label": "计算机ETF"},
    "电子信息": {"etf_symbol": "SH515260", "mapping_label": "电子ETF"},
    "电子元件": {"etf_symbol": "SH515260", "mapping_label": "电子ETF"},
    "光学光电子": {"etf_symbol": "SH515260", "mapping_label": "电子ETF"},
    "游戏": {"etf_symbol": "SZ159869", "mapping_label": "游戏ETF"},
    "游戏Ⅱ": {"etf_symbol": "SZ159869", "mapping_label": "游戏ETF"},
    "电池": {"etf_symbol": "SH515700", "mapping_label": "新能源车ETF"},
    "汽车整车": {"etf_symbol": "SZ159512", "mapping_label": "汽车ETF"},
    "汽车零部件": {"etf_symbol": "SH515700", "mapping_label": "新能源车ETF"},
    "医药商业": {"etf_symbol": "SH512170", "mapping_label": "医疗ETF"},
    "中药": {"etf_symbol": "SH560080", "mapping_label": "中药ETF"},
    "化学制药": {"etf_symbol": "SH512170", "mapping_label": "医疗ETF"},
    "创新药": {"etf_symbol": "SH515120", "mapping_label": "创新药ETF"},
    "创新药及生物类似药": {"etf_symbol": "SH515120", "mapping_label": "创新药ETF"},
    "化肥行业": {"etf_symbol": "SH516020", "mapping_label": "化工ETF"},
    "化学制品": {"etf_symbol": "SH516020", "mapping_label": "化工ETF"},
    "煤炭采选": {"etf_symbol": "SH515220", "mapping_label": "煤炭ETF"},
    "煤炭行业": {"etf_symbol": "SH515220", "mapping_label": "煤炭ETF"},
    "钢铁行业": {"etf_symbol": "SH515210", "mapping_label": "钢铁ETF"},
    "石油行业": {"etf_symbol": "SH561360", "mapping_label": "石油ETF"},
    "水泥建材": {"etf_symbol": "SZ159745", "mapping_label": "建材ETF"},
    "房地产": {"etf_symbol": "SH512200", "mapping_label": "房地产ETF"},
    "房地产开发": {"etf_symbol": "SH512200", "mapping_label": "房地产ETF"},
    "航天航空": {"etf_symbol": "SH512660", "mapping_label": "军工ETF"},
    "航天装备Ⅱ": {"etf_symbol": "SH512660", "mapping_label": "军工ETF"},
    "船舶制造": {"etf_symbol": "SH560710", "mapping_label": "船舶ETF"},
    "机械行业": {"etf_symbol": "SH516960", "mapping_label": "机械ETF"},
    "通用设备": {"etf_symbol": "SH516960", "mapping_label": "机械ETF"},
    "自动化设备": {"etf_symbol": "SH516960", "mapping_label": "机械ETF"},
    "电源设备": {"etf_symbol": "SH516160", "mapping_label": "新能源ETF"},
    "风电设备": {"etf_symbol": "SH516160", "mapping_label": "新能源ETF"},
    "光伏设备": {"etf_symbol": "SH516160", "mapping_label": "新能源ETF"},
    "其他电源设备Ⅱ": {"etf_symbol": "SH516160", "mapping_label": "新能源ETF"},
    "公用事业": {"etf_symbol": "SZ159301", "mapping_label": "公用事业ETF"},
    "燃气": {"etf_symbol": "SZ159301", "mapping_label": "公用事业ETF"},
    "火电": {"etf_symbol": "SZ159301", "mapping_label": "公用事业ETF"},
    "水电": {"etf_symbol": "SZ159301", "mapping_label": "公用事业ETF"},
    "核电": {"etf_symbol": "SZ159301", "mapping_label": "公用事业ETF"},
    "新能源发电": {"etf_symbol": "SZ159301", "mapping_label": "公用事业ETF"},
    "电力行业": {"etf_symbol": "SZ159611", "mapping_label": "电力ETF"},
    "环保工程": {"etf_symbol": "SH512580", "mapping_label": "环保ETF"},
    "环保行业": {"etf_symbol": "SH512580", "mapping_label": "环保ETF"},
    "物流行业": {"etf_symbol": "SH516910", "mapping_label": "物流ETF"},
    "旅游酒店": {"etf_symbol": "SZ159766", "mapping_label": "旅游ETF"},
    "旅游及景区": {"etf_symbol": "SZ159766", "mapping_label": "旅游ETF"},
    "家电行业": {"etf_symbol": "SZ159996", "mapping_label": "家电ETF"},
    "家用轻工": {"etf_symbol": "SH515730", "mapping_label": "家居家电ETF"},
    "酿酒行业": {"etf_symbol": "SH512690", "mapping_label": "酒ETF"},
    "文化传媒": {"etf_symbol": "SH512980", "mapping_label": "传媒ETF"},
    "工程建设": {"etf_symbol": "SH516970", "mapping_label": "基建ETF"},
    "食品饮料": {"etf_symbol": "SH515170", "mapping_label": "食品饮料ETF"},
    "互联网服务": {"etf_symbol": "SZ159729", "mapping_label": "互联网ETF"},
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
STOCK_PRICE_PROXY_SURVIVORSHIP_AUDITED_CHECK = (
    "delisted_inclusive_universe_audit_passed"
)
STOCK_PRICE_PROXY_SURVIVORSHIP_CHECKS = {
    STOCK_PRICE_PROXY_SURVIVORSHIP_CHECK,
    STOCK_PRICE_PROXY_SURVIVORSHIP_AUDITED_CHECK,
}
STOCK_PRICE_PROXY_TRADABILITY_CHECK = "positive_volume_and_limit_lock_screen"
STOCK_PRICE_PROXY_CODE_POLICY: Mapping[str, Any] = {
    "policy_id": "ordinary_a_share_stock_codes_v1",
    "allowed_prefixes": {
        "SH": ["60", "68"],
        "SZ": ["00", "30"],
        "BJ": ["92"],
    },
    "rejected_code_families": [
        "fund",
        "etf",
        "lof",
        "index",
        "legacy_bj_8_prefix",
    ],
    "fund_like_prefix_examples": {
        "SH": ["50", "51", "52"],
        "SZ": ["15", "16", "18"],
    },
    "fallback_action": "stock_target_mapping_missing",
}
MARKDOWN_COVERAGE_MIN_SELECTED_REPORTS = 300
MARKDOWN_COVERAGE_MIN_MARKDOWN_READY = 300
MARKDOWN_COVERAGE_MIN_QUALITY_PASS = 300
MARKDOWN_COVERAGE_MIN_LLM_EXTRACTION_PROCESSED = 100
MARKDOWN_COVERAGE_MIN_INDUSTRY_REPORTS = 80
MARKDOWN_COVERAGE_MIN_STOCK_REPORTS = 80
MARKDOWN_COVERAGE_MIN_STOCK_OUTCOME_120D_READY_REPORTS = 30
MARKDOWN_COVERAGE_MIN_REPORTS_PER_SECTOR_BUCKET = 5
MARKDOWN_COVERAGE_REQUIRED_TIME_BUCKETS = (
    "recent_1y",
    "recent_3y",
    "long_cycle_history",
)
MARKDOWN_COVERAGE_REQUIRED_INSTITUTION_BUCKETS = (
    "head_institution",
    "long_tail_institution",
)
MARKDOWN_COVERAGE_REQUIRED_HORIZON_BUCKETS = (
    "5d",
    "20d",
    "60d",
    "long_horizon",
)
MARKDOWN_COVERAGE_REQUIRED_EVALUABILITY_BUCKETS = (
    "stock_proxy_candidate",
    "industry_proxy_candidate",
    "mapping_gap_candidate",
)
MARKDOWN_COVERAGE_REQUIRED_STOCK_OUTCOME_AGE_BUCKETS = (
    "stock_outcome_120d_calendar_ready",
)
MARKDOWN_QUALITY_MIN_BYTES = 80
MARKDOWN_QUALITY_EMPTY_TABLE_RATIO_MAX = 0.60
MARKDOWN_QUALITY_REPEATED_LINE_RATIO_MAX = 0.45
MARKDOWN_QUALITY_REPEATED_LINE_MIN_COUNT = 4
MARKDOWN_RETRYABLE_GAP_MARKERS = ("mineru", "timeout", "failed", "not_found")
MARKDOWN_FALSE_POSITIVE_RISK_GAPS = {
    "markdown_empty_table_dominant",
    "markdown_repeated_line_noise",
    "markdown_structure_signal_missing",
    "markdown_too_short",
}
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
    exclude_processed_registry_dirs: Sequence[str | Path] = ()
    require_cached_markdown: bool = False
    limit: int | None = None
    min_publish_date: str | None = None
    max_publish_date: str | None = None
    selection_order: Literal["latest", "oldest", "stratified"] = "latest"
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
    vllm_api_key: str | None = None
    qlib_etf_dir: str | Path = DEFAULT_Q_LIB_ETF_PATH
    qlib_stock_dir: str | Path = DEFAULT_Q_LIB_STOCK_PATH
    vllm_timeout_seconds: int = DEFAULT_VLLM_TIMEOUT_SECONDS
    chunk_chars: int = 60_000
    max_chunks: int = 8
    max_llm_output_tokens: int = 4096
    progress_jsonl: bool = False


def _emit_report_intelligence_progress(
    cfg: ReportIntelligenceConfig,
    *,
    event: str,
    run_id: str,
    **fields: Any,
) -> None:
    if not cfg.progress_jsonl:
        return
    payload = {
        "event": event,
        "run_id": run_id,
        **fields,
    }
    print(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        file=sys.stderr,
        flush=True,
    )


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
class AnalyticalFootprintReviewPrepareReport:
    report_id: str
    target_path: str
    output_path: str
    accepted: bool
    overwrite: bool
    requested_limit: int | None
    requested_offset: int
    output_rows: int
    complete_rows: int
    pending_rows: int
    pending_required_fields: Mapping[str, int]
    blockers: Sequence[str]


@dataclass(frozen=True)
class AnalyticalFootprintReviewAssistReport:
    report_id: str
    target_path: str
    reviewed_import_path: str
    jsonl_path: str
    markdown_path: str
    row_count: int
    pending_rows: int
    blockers: Sequence[str]


@dataclass(frozen=True)
class AnalyticalFootprintReviewEvidenceReport:
    report_id: str
    target_path: str
    reviewed_import_path: str
    jsonl_path: str
    markdown_path: str
    requested_limit: int
    requested_offset: int
    row_count: int
    evidence_rows: int
    missing_markdown_rows: int
    blockers: Sequence[str]
    selection_source: str = "priority_sorted_pending"
    review_input_path: str = ""


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


def _read_macro_regime_calendar_rows(registry_dir: Path) -> list[Mapping[str, Any]]:
    blockers: list[str] = []
    rows = _read_registry_jsonl(
        registry_dir / "macro_regime_calendar.jsonl",
        label="macro_regime_calendar",
        blockers=blockers,
    )
    return rows or list(DEFAULT_MACRO_REGIME_CALENDAR_ROWS)


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
    missing: list[str] = []
    for relative in sorted(REPORT_INTELLIGENCE_REQUIRED_PRIVATE_DERIVED_INPUT_PATHS):
        path = _report_intelligence_registry_path(
            root_path=root_path,
            registry_dir=registry_dir,
            relative_path=relative,
        )
        if not path.exists():
            missing.append(relative)
            continue
        if (
            relative in REPORT_INTELLIGENCE_NONEMPTY_PRIVATE_DERIVED_INPUT_PATHS
            and path.stat().st_size == 0
        ):
            missing.append(relative)
            continue
        rows, errors = load_jsonl_with_errors(path, label=relative)
        if errors:
            missing.append(relative)
            continue
        if (
            relative in REPORT_INTELLIGENCE_NONEMPTY_PRIVATE_DERIVED_INPUT_PATHS
            and not any(isinstance(row, Mapping) for row in rows)
        ):
            missing.append(relative)
    return tuple(missing)


def _jsonl_has_mapping_rows(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    rows, errors = load_jsonl_with_errors(path, label=str(path))
    if errors:
        return False
    return any(isinstance(row, Mapping) for row in rows)


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


def _processed_source_ids_from_registry_dirs(
    root_path: Path, registry_dirs: Sequence[str | Path]
) -> tuple[set[str], list[str]]:
    processed: set[str] = set()
    blockers: list[str] = []
    for registry_dir in registry_dirs:
        path = Path(registry_dir)
        if not path.is_absolute():
            path = root_path / path
        status_path = path / "processing_status.jsonl"
        if not status_path.exists():
            blockers.append(
                f"exclude processed registry status missing: {status_path}"
            )
            continue
        raw_rows, parse_blockers = load_jsonl_with_errors(
            status_path,
            label=f"processed registry status {status_path}",
        )
        blockers.extend(parse_blockers)
        for row in _mapping_rows(raw_rows, blockers):
            if row.get("llm_status") != "processed":
                continue
            source_id = str(row.get("source_id") or "").strip()
            if source_id:
                processed.add(source_id)
    return processed, blockers


def _cached_markdown_path_for_source(cache_dir: Path, source_id: object) -> Path:
    return cache_dir / "markdown" / f"{_safe_file_id(str(source_id or ''))}.md"


def _selected_source_rows(
    root_path: Path,
    *,
    source_path: str | Path,
    cache_dir: str | Path,
    source_ids: Sequence[str],
    limit: int | None,
    exclude_source_ids: Sequence[str] = (),
    require_cached_markdown: bool = False,
    min_publish_date: str | None = None,
    max_publish_date: str | None = None,
    selection_order: Literal["latest", "oldest", "stratified"] = "latest",
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
    excluded = {
        str(source_id).strip()
        for source_id in exclude_source_ids
        if str(source_id).strip()
    }
    if excluded:
        rows = [
            row
            for row in rows
            if str(row.get("source_id") or "").strip() not in excluded
        ]
    if require_cached_markdown:
        resolved_cache_dir = (
            Path(cache_dir)
            if Path(cache_dir).is_absolute()
            else root_path / cache_dir
        )
        rows = [
            row
            for row in rows
            if (markdown_path := _cached_markdown_path_for_source(
                resolved_cache_dir,
                row.get("source_id"),
            )).exists()
            and markdown_path.stat().st_size > 0
        ]
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
    if selection_order not in {"latest", "oldest", "stratified"}:
        blockers.append("selection_order must be latest, oldest, or stratified")
        selection_order = "latest"
    rows = sorted(
        rows,
        key=lambda row: (
            str(row.get("publish_date") or ""),
            str(row.get("source_id") or ""),
        ),
        reverse=selection_order == "latest",
    )
    if selection_order == "stratified":
        rows = _stratified_source_rows(
            rows,
            len(rows) if limit is None else max(limit, 0),
        )
        return rows, blockers
    if limit is not None:
        rows = rows[: max(limit, 0)]
    return rows, blockers


def _source_publish_datetime(row: Mapping[str, Any]) -> str:
    publish_date = str(row.get("publish_date") or "").strip()
    if not publish_date:
        return ""
    return publish_date if "T" in publish_date else f"{publish_date}T00:00:00+08:00"


def _stratified_source_values(
    row: Mapping[str, Any],
    *,
    corpus_as_of: datetime | None,
    institution_counts: Mapping[str, int],
    total_reports: int,
) -> tuple[tuple[str, str], ...]:
    metadata_like = {
        **dict(row),
        "publish_datetime": _source_publish_datetime(row),
        "sector": _report_sector_bucket(row),
    }
    report_type = str(row.get("report_type") or "unknown_report_type")
    sector = _report_sector_bucket(row)
    return (
        ("report_type", report_type),
        ("time_bucket", _coverage_time_bucket(metadata_like, corpus_as_of=corpus_as_of)),
        (
            "institution_bucket",
            _coverage_institution_bucket(
                metadata_like,
                institution_counts=institution_counts,
                total_reports=total_reports,
            ),
        ),
        ("sector_bucket", sector),
        (
            "stock_ts_code",
            "stock_ts_code_present"
            if _is_explicit_stock_ts_code(row.get("ts_code"))
            else "stock_ts_code_missing",
        ),
        (
            "stock_outcome_age_bucket",
            _coverage_stock_outcome_age_bucket(
                metadata_like,
                corpus_as_of=corpus_as_of,
            ),
        ),
    )


def _stratified_source_rows(
    rows: Sequence[Mapping[str, Any]],
    limit: int,
) -> list[Mapping[str, Any]]:
    if limit <= 0:
        return []
    total_reports = len(rows)
    selected: list[Mapping[str, Any]] = []
    seen: dict[str, set[str]] = {
        "report_type": set(),
        "time_bucket": set(),
        "institution_bucket": set(),
        "sector_bucket": set(),
        "stock_ts_code": set(),
        "stock_outcome_age_bucket": set(),
    }
    corpus_as_of = _coverage_corpus_as_of(
        [{"publish_datetime": _source_publish_datetime(row)} for row in rows]
    )
    institution_counts = _coverage_institution_counts(rows)
    remaining: list[
        tuple[Mapping[str, Any], tuple[tuple[str, str], ...], tuple[str, str]]
    ] = [
        (
            row,
            _stratified_source_values(
                row,
                corpus_as_of=corpus_as_of,
                institution_counts=institution_counts,
                total_reports=total_reports,
            ),
            (
                str(row.get("publish_date") or ""),
                str(row.get("source_id") or ""),
            ),
        )
        for row in rows
    ]

    while remaining and len(selected) < limit:
        best_index = 0
        best_score: tuple[int, str, str] | None = None
        for index, (_, values, tie_break) in enumerate(remaining):
            coverage_gain = sum(
                value not in seen[dimension] for dimension, value in values
            )
            score = (
                coverage_gain,
                tie_break[0],
                tie_break[1],
            )
            if best_score is None or score > best_score:
                best_score = score
                best_index = index
        row, values, _ = remaining.pop(best_index)
        selected.append(row)
        for dimension, value in values:
            seen[dimension].add(value)
    return selected


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


def _mineru_cached_vlm_model_exists(env: Mapping[str, str]) -> bool:
    hf_home = env.get("HF_HOME")
    if hf_home:
        cache_root = Path(hf_home).expanduser()
    else:
        cache_root = Path.home() / ".cache" / "huggingface"
    model_cache = cache_root / "hub" / MINERU_VLM_HF_CACHE_DIRNAME
    return (model_cache / "refs" / "main").exists() and any(
        (model_cache / "snapshots").glob("*")
    )


def _mineru_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    for key, value in DEFAULT_MINERU_ENV.items():
        env.setdefault(key, value)
    if _mineru_cached_vlm_model_exists(env):
        env.setdefault("HF_HUB_OFFLINE", "1")
        env.setdefault("TRANSFORMERS_OFFLINE", "1")
    return env


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
    env = _mineru_subprocess_env()
    try:
        process = subprocess.Popen(
            list(args),
            cwd=str(cwd),
            env=env,
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
    api_key: str | None = None,
    timeout_seconds: int = 10,
) -> str:
    if explicit_model:
        return explicit_model
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        request = urllib.request.Request(_url(base_url, "models"), headers=headers)
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
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
        "sector": _report_sector_bucket(row),
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
        "must still support each forecast. Extract forecast_claims as concise "
        "source-grounded research claims synthesized from the whole Markdown "
        "chunk or a coherent paragraph, not as isolated sentence snippets. A "
        "valid claim should connect background/regime, mechanism/action, company "
        "capability when relevant, and potential market or fundamental impact "
        "when the source supports that connection. Split regime into macro "
        "environment and industry-cycle regime when the source supports both: "
        "macro regime includes rate-cut cycles, monetary/liquidity stance, "
        "credit cycle, fiscal or regulatory policy, FX/dollar cycle, and growth "
        "or inflation environment; industry-cycle regime includes sector supply "
        "tightness, demand-driver transition, inventory, capacity, price, "
        "competition, prosperity, or technology cycles. Keep those regimes "
        "separate from company-specific capability or action: sector demand "
        "growth is a regime, while lab rollout, capacity, channel, technology, "
        "cost control, order backlog, or management execution is company "
        "capability/action. Also keep mechanism separate from both regime and "
        "impact: a mechanism is the transmission channel such as demand pull, "
        "price/cost pass-through, margin expansion, capacity release, market-share "
        "gain, technology/productivity improvement, policy/liquidity transmission, "
        "or valuation repricing. For Chinese reports, write claim_text in Chinese. Do not "
        "put boilerplate risk warnings or purely historical descriptive facts "
        "into forecast_claims. Do not emit general scientific, clinical, public "
        "health, or policy recommendations as forecast_claims unless the source "
        "connects them to company/sector demand, revenue, profit, valuation, "
        "stock return, industry prosperity, or an investment view. /no_think"
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
        "Only emit forecast_claims for source-grounded research claims with at "
        "least one of: causal/economic mechanism, regime condition, explicit or "
        "clearly implied forward view, expected target impact, or actionable "
        "investment view. The claim_text should be a compact synthesis over the "
        "relevant paragraph/window when needed. It does not need to be a verbatim "
        "sentence, but every element must be supported by the cited source span. "
        "For Chinese source text, output claim_text in Chinese and keep variable "
        "or schema ids in English only where the schema requires ids. "
        "Prefer claims of the form: under <macro regime if present> and "
        "<industry-cycle regime if present>, <mechanism/action> "
        "and, for stock reports, <company capability/action> are expected to "
        "affect <target/fundamental/return> through <channel>. Do not merge "
        "macro regime, industry-cycle regime, and company capability into one "
        "undifferentiated cause: 'the Fed entered a rate-cut cycle' or 'China "
        "stepped up counter-cyclical monetary policy' is macro regime; 'global "
        "copper supply is structurally tight while demand drivers are shifting' "
        "is industry-cycle regime; 'company labs reaching designed utilization' "
        "is company capability/action. "
        "Make the economic mechanism explicit when supported: identify whether "
        "the claim works through demand pull, price/cost pass-through, capacity "
        "release, margin expansion, market-share gain, technology/productivity, "
        "policy/liquidity transmission, or valuation repricing. "
        "A forecast_claim must have a finance-relevant target impact: demand, "
        "orders, revenue, margin, profit, valuation, stock return, sector return, "
        "industry prosperity, credit growth, liquidity, or explicit investment "
        "view. General clinical, public-health, scientific, regulatory, or policy "
        "recommendations without such market/fundamental linkage belong in "
        "analytical_footprints, not forecast_claims. "
        "Do not emit forecast_claims for generic boilerplate such as '风险提示：...' "
        "or for pure historical/statistical descriptions such as price-change "
        "tables, ROE rankings, current margins, asset-liability ratios, and "
        "market-performance summaries unless the surrounding paragraph links "
        "those facts to a forward impact or mechanism. Such descriptive facts may "
        "appear in analytical_footprints as context, not forecast_claims.\n"
        "For stock reports, if Report metadata.ts_code is present and the chunk "
        "contains a forecast, rating, or investment view for that same company, "
        "set target.target_type='stock' and target.target_id to metadata.ts_code. "
        "For industry reports, if Report metadata.industry or metadata.query_key "
        "names the covered sector and the chunk contains an investment view, "
        "outlook, prosperity-cycle view, rating change, or relative-performance "
        "call for that sector, set target.target_type='sector' and target.target_id "
        "to the metadata sector string. For industry directions, use positive only "
        "when the source text is bullish, constructive, recommends overweight, "
        "expects upside, expects prosperity improvement, or expects the sector to "
        "outperform; use negative only when the source text is bearish, defensive, "
        "recommends underweight, expects downside, expects prosperity deterioration, "
        "or expects underperformance. Use neutral, ambiguous, or unknown when the "
        "chunk is balanced, only descriptive, or lacks a clear directional view. "
        "If the text names a benchmark, include benchmark_id; otherwise use "
        "benchmark_type='broad_market' only when the text frames a relative call "
        "against the market. Never invent a horizon; keep horizon unknown when "
        "the source text has no explicit or clearly implied time window. When "
        "the text explicitly says windows such as 2026-2028年, 未来三年, 年内, "
        "未来6个月, 短期, 中期, 中长期, or 长期, encode that in horizon rather "
        "than leaving it empty. Fill metric_proxy_mapping with source-supported "
        "finance proxies such as stock_forward_return, industry_etf_forward_return, "
        "relative_alpha, revenue_growth, earnings_growth, margin_profitability, "
        "valuation_multiple, demand_growth, industry_prosperity, liquidity_credit_condition, "
        "or commodity_price_cycle. Leave the list empty only when the claim has "
        "no finance/fundamental/return proxy in the source text.\n"
        "analytical_footprints fields: topic, indicator_mentions, "
        "analysis_patterns, target_agent_candidates. Mark each mention/step "
        "with source_grounded true/false when possible. For analytical_footprints, "
        "do not leave indicator_mentions empty when the footprint depends on "
        "measurable evidence, validation data, or market/fundamental proxies; "
        "name the indicator, canonical metric candidate, data source, frequency, "
        "transformation, role in the argument, and whether it is directly "
        "source-grounded. Use unknown only for fields that are truly absent.\n"
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
    api_key: str | None = None,
    timeout_seconds: int = 120,
    max_output_tokens: int = 4096,
) -> Mapping[str, Any]:
    resolved_model = resolve_vllm_model(
        base_url,
        explicit_model=model,
        api_key=api_key,
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
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        _url(base_url, "chat/completions"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
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


def _threshold_shortfall(
    *,
    current: int,
    target: int,
    blocker: str,
    next_action: str,
) -> dict[str, Any]:
    return {
        "current": max(0, int(current)),
        "target": max(0, int(target)),
        "remaining": max(0, int(target) - int(current)),
        "blocker": blocker,
        "next_action": next_action,
    }


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


def _is_forecast_claim_candidate_text(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized or _is_boilerplate_risk_warning_text(normalized):
        return False
    lowered = normalized.lower()
    mechanism_hits = sum(
        1 for term in FORECAST_CLAIM_MECHANISM_TERMS if term in normalized
    )
    descriptive_hits = sum(
        1 for term in FORECAST_CLAIM_DESCRIPTIVE_ONLY_TERMS if term in normalized
    )
    numeric_heavy = len(re.findall(r"\d+(?:\.\d+)?%?", normalized)) >= 3
    if mechanism_hits == 0 and (descriptive_hits or numeric_heavy):
        return False
    if numeric_heavy and descriptive_hits and mechanism_hits < 2:
        return False
    if not any(term.lower() in lowered for term in FORECAST_CLAIM_FINANCE_IMPACT_TERMS):
        return False
    return True


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


_CHINESE_NUMBER_VALUES: Mapping[str, int] = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _parse_chinese_integer_text(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if text in _CHINESE_NUMBER_VALUES:
        return _CHINESE_NUMBER_VALUES[text]
    if text == "十":
        return 10
    if "十" in text:
        left, _, right = text.partition("十")
        tens = _CHINESE_NUMBER_VALUES.get(left, 1 if not left else -1)
        ones = _CHINESE_NUMBER_VALUES.get(right, 0 if not right else -1)
        if tens >= 0 and ones >= 0:
            return tens * 10 + ones
    return None


def _parse_float_text(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _parse_duration_value_text(value: str) -> float | None:
    text = str(value or "").strip()
    if text == "半":
        return 0.5
    parsed = _parse_float_text(text)
    if parsed is not None:
        return parsed
    chinese = _parse_chinese_integer_text(text)
    return float(chinese) if chinese is not None else None


def _days_until_year_end(publish_date: str, target_year: int) -> int | None:
    try:
        publish_dt = datetime.strptime(str(publish_date or ""), "%Y-%m-%d")
    except ValueError:
        return None
    target_dt = datetime(target_year, 12, 31)
    days = (target_dt - publish_dt).days
    return days if days > 0 else None


def _year_range_days_without_publish_date(start_year: int, end_year: int) -> int | None:
    if end_year < start_year:
        return None
    return int(round((end_year - start_year + 1) * 365.25))


def _horizon_days_from_mapping(horizon: Mapping[str, Any]) -> int | None:
    for key in ("preferred_days", "max_days", "min_days"):
        try:
            return int(horizon[key])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _horizon_exceeds_reasonable_bound(horizon: Mapping[str, Any]) -> bool:
    days = _horizon_days_from_mapping(horizon)
    return days is not None and days > MAX_REASONABLE_FORECAST_HORIZON_DAYS


def _infer_horizon_from_claim_text(
    claim_text: str,
    publish_date: str,
) -> dict[str, Any]:
    text = str(claim_text or "")
    relative_patterns = (
        r"未来\s*(?P<value>\d+(?:\.\d+)?|[一二两三四五六七八九十]+|半)\s*(?:个)?(?P<unit>交易日|天|日|周|个月|月|年)(?:内|以内|左右|附近)?",
        r"(?P<value>\d+(?:\.\d+)?|[一二两三四五六七八九十]+|半)\s*(?:个)?(?P<unit>交易日|天|日|周|个月|月|年)(?:内|以内)",
    )
    for pattern in relative_patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        raw_value = match.group("value")
        if match.group("unit") == "年" and re.fullmatch(r"20\d{2}", raw_value):
            continue
        value = _parse_duration_value_text(raw_value)
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

    range_match = re.search(
        r"(20\d{2})\s*(?:-|—|~|至|到)\s*(20\d{2})\s*年",
        text,
    )
    if range_match:
        start_year = int(range_match.group(1))
        end_year = int(range_match.group(2))
        days = _days_until_year_end(publish_date, end_year)
        if days is None:
            days = _year_range_days_without_publish_date(start_year, end_year)
        if days is not None:
            return {
                "max_days": days,
                "unit": "calendar_day",
                "source": "explicit_claim_text",
                "source_text": range_match.group(0).strip(),
            }

    absolute_match = re.search(r"(?:预计|预期|有望|计划|将)?\s*(?:到|至|截至)\s*(20\d{2})\s*年", text)
    if absolute_match:
        target_year = int(absolute_match.group(1))
        days = _days_until_year_end(publish_date, target_year)
        if days is None:
            days = _year_range_days_without_publish_date(target_year, target_year)
        if days is not None:
            return {
                "max_days": days,
                "unit": "calendar_day",
                "source": "explicit_claim_text",
                "source_text": absolute_match.group(0).strip(),
            }
    if re.search(r"(?:年内|今年内)", text):
        try:
            publish_year = datetime.strptime(str(publish_date or ""), "%Y-%m-%d").year
        except ValueError:
            publish_year = None
        if publish_year is not None:
            days = _days_until_year_end(publish_date, publish_year)
            if days is not None:
                return {
                    "max_days": days,
                    "unit": "calendar_day",
                    "source": "explicit_claim_text",
                    "source_text": "年内",
                }
        year_in_text = re.search(r"(20\d{2})\s*年内", text)
        if year_in_text:
            return {
                "max_days": 365,
                "unit": "calendar_day",
                "source": "explicit_claim_text_missing_publish_date",
                "source_text": year_in_text.group(0),
            }
    qualitative_horizons: tuple[tuple[str, int], ...] = (
        ("短期", 20),
        ("中短期", 60),
        ("中长期", 120),
        ("中期", 60),
        ("长期", 120),
    )
    for source_text, days in qualitative_horizons:
        if source_text in text:
            return {
                "preferred_days": days,
                "unit": "trading_day",
                "source": "qualitative_claim_text",
                "source_text": source_text,
            }
    return {}


METRIC_PROXY_INFERENCE_RULES: tuple[tuple[str, str], ...] = (
    (r"营收|营业收入|收入增长|销售收入|收入端|revenue", "revenue_growth"),
    (r"归母净利润|净利润|利润增长|盈利增长|业绩增长|利润端|earnings", "earnings_growth"),
    (r"毛利率|净利率|费用率|成本下降|降本|盈利能力|margin", "margin_profitability"),
    (r"估值|目标价|市盈率|市净率|\bpe\b|\bpb\b|valuation", "valuation_multiple"),
    (r"需求|订单|销量|出货|客流|装机|交付|销售量", "demand_growth"),
    (r"景气|景气度|行业周期|超级周期|产业周期|繁荣", "industry_prosperity"),
    (r"供需|库存|产能|价格中枢|价格维持|涨价|降价|商品价格", "commodity_price_cycle"),
    (r"利率|流动性|信用|社融|信贷|货币政策|资金面", "liquidity_credit_condition"),
)


CLAIM_REGIME_CONTEXT_RE = re.compile(
    r"行业|产业|市场|需求|供给|供需|景气|周期|政策|利率|流动性|库存|产能|价格中枢|竞争格局|宏观",
    flags=re.IGNORECASE,
)
CLAIM_MACRO_REGIME_RULES: tuple[tuple[str, str], ...] = (
    ("us_rate_cut_cycle", r"美国|美联储|Fed|FED|降息周期|降息|联邦基金利率"),
    (
        "china_countercyclical_policy",
        r"中国[^。；，,]{0,24}(?:逆周期|货币政策|稳增长|稳经济|政策加码|政策发力)|"
        r"国内[^。；，,]{0,24}(?:逆周期|货币政策|稳增长|稳经济|政策加码|政策发力)|"
        r"逆周期|稳增长|稳经济|政策加码|政策发力",
    ),
    ("monetary_liquidity_condition", r"货币政策|流动性|资金面|公开市场|净投放|DR007|央行|PBOC"),
    ("credit_cycle", r"信用扩张|信用收缩|社融|信贷|融资需求|信用周期|信用利差"),
    ("fx_usd_cycle", r"美元|汇率|人民币|美元指数|外汇"),
    ("global_growth_inflation", r"全球经济|海外经济|通胀|再通胀|衰退|复苏|PMI"),
    ("fiscal_policy", r"财政|专项债|国债|赤字|税收|补贴"),
    ("regulatory_policy", r"监管|产业政策|政策支持|政策约束|政策放松"),
)
DEFAULT_MACRO_REGIME_CALENDAR_ROWS: tuple[Mapping[str, Any], ...] = (
    {
        "regime_id": "MACRO-REGIME-US-RATE-CUT-20240918",
        "regime_type": "us_rate_cut_cycle",
        "start_date": "2024-09-18",
        "end_date": "2025-12-31",
        "source": "Fed rate-cut cycle after the September 2024 FOMC cut",
        "source_url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20240918a.htm",
        "pit_available": True,
        "policy": (
            "macro regime calendar is public aggregate governance metadata; it may "
            "supplement forecast claims by PIT as_of_datetime but must not claim "
            "source-text grounding"
        ),
        "version": 1,
    },
    {
        "regime_id": "MACRO-REGIME-US-RATE-CUT-20260101",
        "regime_type": "us_rate_cut_cycle",
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "source": "US policy-rate cycle remained in a post-cut/easing-evaluation window after 2025 cuts",
        "source_url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20251210a.htm",
        "pit_available": True,
        "policy": (
            "macro regime calendar is public aggregate governance metadata; it may "
            "supplement forecast claims by PIT as_of_datetime but must not claim "
            "source-text grounding"
        ),
        "version": 1,
    },
    {
        "regime_id": "MACRO-REGIME-CN-COUNTERCYCLICAL-20240924",
        "regime_type": "china_countercyclical_policy",
        "start_date": "2024-09-24",
        "end_date": "2025-12-31",
        "source": (
            "China counter-cyclical policy support after the September 2024 "
            "policy package"
        ),
        "pit_available": True,
        "policy": (
            "macro regime calendar is public aggregate governance metadata; it may "
            "supplement forecast claims by PIT as_of_datetime but must not claim "
            "source-text grounding"
        ),
        "version": 1,
    },
    {
        "regime_id": "MACRO-REGIME-CN-MONETARY-LIQUIDITY-20240924",
        "regime_type": "monetary_liquidity_condition",
        "start_date": "2024-09-24",
        "end_date": "2025-12-31",
        "source": (
            "China monetary-policy counter-cyclical support after the September "
            "2024 policy package"
        ),
        "pit_available": True,
        "policy": (
            "macro regime calendar is public aggregate governance metadata; it may "
            "supplement forecast claims by PIT as_of_datetime but must not claim "
            "source-text grounding"
        ),
        "version": 1,
    },
)
CLAIM_INDUSTRY_CYCLE_REGIME_RULES: tuple[tuple[str, str], ...] = (
    (
        "supply_tightness",
        r"供给.*偏紧|供应.*偏紧|供给约束|供给收缩|供应短缺|产能受限|"
        r"供给.*紧张|供应.*紧张|供需.*错配",
    ),
    ("demand_transition", r"需求动能切换|需求结构变化|新需求|传统需求|新能源需求|AI需求|下游需求"),
    ("industry_demand_growth", r"行业需求持续增长|产业需求持续增长|需求持续增长|需求增长|需求改善"),
    ("inventory_cycle", r"库存|补库|去库|库存周期"),
    ("capacity_cycle", r"行业产能|产业产能|产能周期|产能过剩|产能出清|产能受限|产能利用率"),
    (
        "raw_material_cost_pressure",
        r"原材料价格|投入成本|成本上升|成本压力|铁矿石|炼焦煤|天然橡胶|丁基橡胶",
    ),
    ("price_cycle", r"价格周期|价格中枢|涨价|降价|煤价|铜价|金属价格|商品价格|价格.*上涨"),
    ("competition_cycle", r"竞争格局|集中度|价格战|格局改善|份额|结构分化|业绩分化"),
    ("prosperity_cycle", r"景气|景气度|行业周期|产业周期|超级周期|盈利修复|盈利质量"),
    ("technology_cycle", r"技术周期|产品周期|AI周期|AI技术|算力周期|推理算力|AIGC|创新周期|算力网络|词元生产"),
    ("business_model_shift", r"商业模式|业务结构|收入结构|收入来源|自营业务|高质量发展阶段"),
    ("industry_valuation_cycle", r"估值处于历史低位|安全边际|估值修复|估值提升|估值重估"),
    ("import_substitution_cycle", r"国产替代|进口替代|贸易逆差"),
    ("industry_policy_catalyst", r"政策催化|政策支持|出口限制|产业政策"),
    ("globalization_export_cycle", r"出口高增|出海|海外订单|全球化|国际业务"),
    ("end_market_order_cycle", r"客户.*承诺|客户需求|订单弹性|订单增长"),
    ("energy_hydrology_cycle", r"来水|水文|风光|装机|消纳|特高压"),
)


def _as_of_date_key(value: Any) -> str:
    parsed = _parse_pit_datetime(value)
    if parsed is not None:
        return parsed.date().isoformat()
    text = str(value or "").strip()
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    return match.group(0) if match else ""


def _as_of_date_macro_regime_types(
    as_of_datetime: Any,
    macro_regime_calendar_rows: Sequence[Mapping[str, Any]] = (),
) -> tuple[list[str], dict[str, str]]:
    regime_types, sources, _details = _as_of_date_macro_regime_context(
        as_of_datetime,
        macro_regime_calendar_rows=macro_regime_calendar_rows,
    )
    return regime_types, sources


def _as_of_date_macro_regime_context(
    as_of_datetime: Any,
    macro_regime_calendar_rows: Sequence[Mapping[str, Any]] = (),
) -> tuple[list[str], dict[str, str], list[dict[str, Any]]]:
    date_key = _as_of_date_key(as_of_datetime)
    if not date_key:
        return [], {}, []
    regime_types: list[str] = []
    sources: dict[str, str] = {}
    details: list[dict[str, Any]] = []
    rows = macro_regime_calendar_rows or DEFAULT_MACRO_REGIME_CALENDAR_ROWS
    for row in rows:
        regime_id = str(row.get("regime_id") or "").strip()
        regime_type = str(row.get("regime_type") or "").strip()
        start_date = str(row.get("start_date") or "").strip()
        end_date = str(row.get("end_date") or "").strip()
        note = str(row.get("source") or "").strip()
        if not regime_type or not start_date or not end_date:
            continue
        if row.get("pit_available") is not True:
            continue
        if start_date <= date_key <= end_date:
            regime_types.append(regime_type)
            sources[regime_type] = f"as_of_date:{date_key}; {note}"
            details.append(
                {
                    "regime_id": regime_id,
                    "regime_type": regime_type,
                    "as_of_date": date_key,
                    "start_date": start_date,
                    "end_date": end_date,
                    "source": note,
                    "source_url": str(row.get("source_url") or "").strip(),
                    "source_basis": "as_of_date",
                    "source_text_grounded": False,
                    "pit_available": True,
                    "policy": str(row.get("policy") or "").strip(),
                }
            )
    deduped_types = list(dict.fromkeys(regime_types))
    deduped_details: list[dict[str, Any]] = []
    seen_details: set[tuple[str, str]] = set()
    for detail in details:
        key = (
            str(detail.get("regime_id") or ""),
            str(detail.get("regime_type") or ""),
        )
        if key in seen_details:
            continue
        seen_details.add(key)
        deduped_details.append(detail)
    return deduped_types, sources, deduped_details
CLAIM_COMPANY_CAPABILITY_RE = re.compile(
    r"公司|自身|实验室|投产|达效|全国布局|产能利用|渠道|客户|订单|技术|研发|产品|费用管控|降本|管理|执行|市占率|份额",
    flags=re.IGNORECASE,
)
CLAIM_MARKET_FUNDAMENTAL_IMPACT_RE = re.compile(
    r"营收|营业收入|收入|利润|盈利|业绩|EPS|毛利率|净利率|估值修复|估值溢价|估值提升|估值重估|价值重估|目标价|股价|回报|收益|跑赢|跑输|景气度|需求增长|订单增长|成长空间",
    flags=re.IGNORECASE,
)
CLAIM_MECHANISM_CHANNEL_RULES: tuple[tuple[str, str], ...] = (
    ("demand_pull", r"需求|订单|销量|出货|客流|装机|交付|下游|出口"),
    ("price_cost_pass_through", r"价格|涨价|降价|成本|原材料|煤价|油价|运价|费用率"),
    ("margin_expansion_or_pressure", r"毛利率|净利率|利润率|盈利能力|利润空间|费用率|降本"),
    ("capacity_release_or_supply", r"产能|投产|达效|扩产|产量|供给|供应|库存|利用率"),
    ("market_share_or_competition", r"市占率|份额|竞争格局|龙头|集中度|替代|进口替代"),
    ("technology_productivity", r"技术|研发|效率|算力|模型|自动化|数字化|AI|推理优化"),
    (
        "policy_liquidity_transmission",
        r"政策|监管|利率|流动性|信用扩张|信用收缩|社融|信贷|资金面|公开市场|净投放|DR007|PBOC|央行",
    ),
    ("valuation_repricing", r"估值修复|估值溢价|估值提升|估值重估|价值重估|目标价|评级"),
    ("business_mix_shift", r"业务占比|业务结构|收入结构|配件业务|耗材|自营业务|软件|硬件|服务"),
    ("overseas_expansion", r"海外|出海|出口|外销"),
    ("tax_or_subsidy_benefit", r"税率|所得税|税收|补贴"),
)
CLAIM_MECHANISM_ACTION_RULES: tuple[tuple[str, str], ...] = (
    ("expand_capacity_or_coverage", r"扩充|扩产|投产|达效|布局|拓展|建设|注入"),
    (
        "optimize_cost_or_efficiency",
        r"降本|控费|费用管控|费用率下降|管理费用率下降|财务费用率下降|"
        r"控制成本|成本控制|提质增效|效率提升|优化|精简",
    ),
    ("pass_through_price_or_cost", r"传导|转嫁|报价|价格中枢|成本上升|涨价"),
    ("upgrade_product_or_technology", r"升级|研发|创新|技术|产品力|推理优化|数字化"),
    ("gain_share_or_substitute", r"份额提升|市占率|替代|进口替代|渠道|客户"),
    (
        "receive_policy_or_liquidity_impulse",
        r"政策支持|监管放松|流动性改善|信用扩张|资金流入|净投放改善|DR007回落|资金面改善",
    ),
    ("reprice_valuation_or_rating", r"估值修复|估值溢价|估值提升|价值重估|评级|买入|增持"),
    ("shift_business_mix", r"占比提升|结构优化|收入来源|业务增长|稳定增长"),
    ("expand_overseas_market", r"海外|出海|出口|外销"),
)


def _mechanism_impact_variables(
    metric_proxy_mapping: Sequence[Any],
    claim_text: str,
) -> list[str]:
    variables = [
        str(item).strip()
        for item in metric_proxy_mapping
        if str(item or "").strip()
    ]
    if variables:
        return list(dict.fromkeys(variables))
    text = re.sub(r"\s+", " ", str(claim_text or ""))
    inferred: list[str] = []
    for pattern, metric in METRIC_PROXY_INFERENCE_RULES:
        if re.search(pattern, text, flags=re.IGNORECASE):
            inferred.append(metric)
    return list(dict.fromkeys(inferred))


def _infer_claim_mechanism_roles(
    claim_text: str,
    *,
    target: Mapping[str, Any],
    metric_proxy_mapping: Sequence[Any],
) -> dict[str, Any]:
    text = re.sub(r"\s+", " ", str(claim_text or ""))
    channels = [
        channel
        for channel, pattern in CLAIM_MECHANISM_CHANNEL_RULES
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]
    actions = [
        action
        for action, pattern in CLAIM_MECHANISM_ACTION_RULES
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]
    impact_variables = _mechanism_impact_variables(metric_proxy_mapping, text)
    target_type = str(target.get("target_type") or "").strip().lower() or "unknown"
    has_mechanism = bool(channels or actions)
    connects_to_impact = has_mechanism and bool(impact_variables)
    return {
        "channels": channels,
        "actions": actions,
        "impact_variables": impact_variables,
        "has_economic_mechanism": has_mechanism,
        "mechanism_connects_to_evaluable_impact": connects_to_impact,
        "possible_operational_only_mechanism": has_mechanism and not connects_to_impact,
        "target_type": target_type,
        "mechanism_policy": "separate_regime_mechanism_capability_and_impact",
    }


def _infer_claim_component_roles(
    claim_text: str,
    *,
    target: Mapping[str, Any],
    as_of_datetime: Any = "",
    macro_regime_calendar_rows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    text = re.sub(r"\s+", " ", str(claim_text or ""))
    text_macro_regime_types = [
        regime_type
        for regime_type, pattern in CLAIM_MACRO_REGIME_RULES
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]
    (
        date_macro_regime_types,
        date_macro_regime_sources,
        date_macro_regime_details,
    ) = (
        _as_of_date_macro_regime_context(
            as_of_datetime,
            macro_regime_calendar_rows=macro_regime_calendar_rows,
        )
    )
    macro_regime_types = list(
        dict.fromkeys([*text_macro_regime_types, *date_macro_regime_types])
    )
    macro_regime_sources = {
        regime_type: "source_text" for regime_type in text_macro_regime_types
    }
    for regime_type, source in date_macro_regime_sources.items():
        macro_regime_sources.setdefault(regime_type, source)
    industry_cycle_regime_types = [
        regime_type
        for regime_type, pattern in CLAIM_INDUSTRY_CYCLE_REGIME_RULES
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]
    has_company_capability = bool(CLAIM_COMPANY_CAPABILITY_RE.search(text))
    generic_regime_context = bool(CLAIM_REGIME_CONTEXT_RE.search(text))
    has_regime = bool(
        macro_regime_types
        or industry_cycle_regime_types
        or (generic_regime_context and not has_company_capability)
    )
    target_type = str(target.get("target_type") or "").strip().lower()
    return {
        "has_regime_context": has_regime,
        "has_macro_regime_context": bool(macro_regime_types),
        "has_industry_cycle_regime_context": bool(industry_cycle_regime_types),
        "regime_context_types": list(
            dict.fromkeys([*macro_regime_types, *industry_cycle_regime_types])
        ),
        "macro_regime_context_types": macro_regime_types,
        "source_text_macro_regime_context_types": text_macro_regime_types,
        "as_of_date_macro_regime_context_types": date_macro_regime_types,
        "as_of_date_macro_regime_context_details": date_macro_regime_details,
        "macro_regime_context_sources": macro_regime_sources,
        "industry_cycle_regime_context_types": industry_cycle_regime_types,
        "has_company_capability_or_action": has_company_capability,
        "has_market_or_fundamental_impact": bool(
            CLAIM_MARKET_FUNDAMENTAL_IMPACT_RE.search(text)
        ),
        "target_type": target_type or "unknown",
        "mixed_regime_and_company_capability": (
            target_type == "stock" and has_regime and has_company_capability
        ),
        "role_policy": (
            "separate_macro_regime_industry_cycle_regime_company_capability_"
            "mechanism_and_impact"
        ),
        "as_of_regime_policy": (
            "macro regime may be inferred from PIT as_of_datetime; industry-cycle "
            "regime must be source-text derived"
        ),
    }


def _target_return_metric(target: Mapping[str, Any], claim_text: str) -> str:
    target_type = str(target.get("target_type") or "").strip().lower()
    if target_type == "stock":
        return "stock_forward_return"
    if target_type in {"sector", "industry"}:
        return "industry_etf_forward_return"
    if target_type == "commodity":
        return "commodity_spot_price"
    if re.search(r"股价|股票|买入|增持|减持|目标价", claim_text):
        return "stock_forward_return"
    if re.search(r"板块|行业|超配|低配|跑赢|跑输", claim_text):
        return "industry_etf_forward_return"
    return "forward_return_proxy"


def _normalize_metric_proxy_mapping(
    value: Any,
    *,
    claim_text: str,
    target: Mapping[str, Any],
) -> tuple[list[str], bool]:
    records = [
        str(item).strip()
        for item in _ensure_list(value)
        if str(item or "").strip()
        and str(item or "").strip().lower() not in {"unknown", "n/a", "na", "none"}
    ]
    inferred: list[str] = []
    normalized_text = re.sub(r"\s+", " ", str(claim_text or ""))
    for pattern, metric in METRIC_PROXY_INFERENCE_RULES:
        if re.search(pattern, normalized_text, flags=re.IGNORECASE):
            inferred.append(metric)
    if (
        str(target.get("target_type") or "").strip().lower() == "commodity"
        and "commodity_price_cycle" in inferred
    ):
        inferred.append("commodity_spot_price")
    if re.search(
        r"股价|股价表现|跑赢|跑输|超额收益|收益率|上涨|下跌|回报|买入|增持|减持|评级|目标价",
        normalized_text,
    ):
        inferred.append(_target_return_metric(target, normalized_text))
    if re.search(r"跑赢|跑输|超额收益|相对收益|alpha|阿尔法", normalized_text, flags=re.IGNORECASE):
        inferred.append("relative_alpha")

    merged: list[str] = []
    seen: set[str] = set()
    for item in [*records, *inferred]:
        key = item.lower()
        if key not in seen:
            merged.append(item)
            seen.add(key)
    return merged, bool(inferred and not records)


def _normalize_or_infer_horizon(
    horizon: Any,
    *,
    claim_text: str,
    publish_date: str,
) -> tuple[dict[str, Any], bool]:
    normalized = _ensure_mapping(horizon)
    invalid_model_horizon = _horizon_exceeds_reasonable_bound(normalized)
    if _horizon_bucket(normalized) != "unknown" and not invalid_model_horizon:
        return normalized, False
    inferred = _infer_horizon_from_claim_text(claim_text, publish_date)
    if inferred:
        if invalid_model_horizon:
            inferred["invalid_model_horizon_replaced"] = True
        return inferred, True
    if invalid_model_horizon:
        return {}, False
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
    macro_regime_calendar_rows: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in _ensure_list(payload.get("forecast_claims")):
        claim = _ensure_mapping(item)
        raw_claim_text = _record_text(claim, "claim_text", "text")
        if not raw_claim_text:
            continue
        if not _is_forecast_claim_candidate_text(raw_claim_text):
            continue
        claim_text, claim_text_truncated = _bounded_claim_text(raw_claim_text)
        horizon, horizon_inferred = _normalize_or_infer_horizon(
            claim.get("horizon"),
            claim_text=raw_claim_text,
            publish_date=str(row.get("publish_date") or ""),
        )
        target = _ensure_mapping(claim.get("target"))
        metric_proxy_mapping, metric_proxy_inferred = _normalize_metric_proxy_mapping(
            claim.get("metric_proxy_mapping"),
            claim_text=raw_claim_text,
            target=target,
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
            "target": target,
            "benchmark": _ensure_mapping(claim.get("benchmark")),
            "direction": _normalize_forecast_direction(claim.get("direction")),
            "horizon": horizon,
            "signal_datetime": str(row.get("publish_date") or ""),
            "entry_rule": _ensure_mapping(claim.get("entry_rule")),
            "explicitness": str(claim.get("explicitness") or "unknown"),
            "source_conviction": str(claim.get("source_conviction") or "unknown"),
            "metric_proxy_mapping": metric_proxy_mapping,
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
        record["extraction_quality"]["claim_component_roles"] = (
            _infer_claim_component_roles(
                raw_claim_text,
                target=target,
                as_of_datetime=row.get("publish_date"),
                macro_regime_calendar_rows=macro_regime_calendar_rows,
            )
        )
        record["extraction_quality"]["claim_mechanism_roles"] = (
            _infer_claim_mechanism_roles(
                raw_claim_text,
                target=target,
                metric_proxy_mapping=metric_proxy_mapping,
            )
        )
        if horizon_inferred:
            record["extraction_quality"]["horizon_inferred_from_claim_text"] = True
            record["extraction_quality"]["horizon_inference_source_text"] = horizon.get(
                "source_text",
                "",
            )
        if metric_proxy_inferred:
            record["extraction_quality"][
                "metric_proxy_mapping_inferred_from_claim_text"
            ] = True
        mapping_gaps = _forecast_mapping_gaps(record)
        if mapping_gaps:
            record["forecast_testability"] = "insufficient_mapping"
            record["extraction_quality"]["mapping_gaps"] = mapping_gaps
            record["extraction_quality"]["needs_human_review"] = True
        records.append(record)
    return records


def _refresh_forecast_mapping_governance(
    forecast_rows: Sequence[Mapping[str, Any]],
    *,
    macro_regime_calendar_rows: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    refreshed_rows: list[dict[str, Any]] = []
    for row in forecast_rows:
        refreshed = dict(row)
        claim_text = str(refreshed.get("claim_text") or "")
        if not _is_forecast_claim_candidate_text(claim_text):
            continue
        horizon, horizon_inferred = _normalize_or_infer_horizon(
            refreshed.get("horizon"),
            claim_text=claim_text,
            publish_date=str(
                refreshed.get("signal_datetime")
                or refreshed.get("publish_date")
                or "",
            ),
        )
        refreshed["horizon"] = horizon
        extraction_quality = dict(_ensure_mapping(refreshed.get("extraction_quality")))
        metric_proxy_mapping, metric_proxy_inferred = _normalize_metric_proxy_mapping(
            refreshed.get("metric_proxy_mapping"),
            claim_text=claim_text,
            target=_ensure_mapping(refreshed.get("target")),
        )
        refreshed["metric_proxy_mapping"] = metric_proxy_mapping
        if horizon_inferred:
            extraction_quality["horizon_inferred_from_claim_text"] = True
            extraction_quality["horizon_inference_source_text"] = horizon.get(
                "source_text",
                "",
            )
        if metric_proxy_inferred:
            extraction_quality["metric_proxy_mapping_inferred_from_claim_text"] = True
        extraction_quality["claim_component_roles"] = _infer_claim_component_roles(
            claim_text,
            target=_ensure_mapping(refreshed.get("target")),
            as_of_datetime=(
                refreshed.get("signal_datetime")
                or refreshed.get("publish_date")
                or ""
            ),
            macro_regime_calendar_rows=macro_regime_calendar_rows,
        )
        extraction_quality["claim_mechanism_roles"] = _infer_claim_mechanism_roles(
            claim_text,
            target=_ensure_mapping(refreshed.get("target")),
            metric_proxy_mapping=metric_proxy_mapping,
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
            "sector": _report_sector_bucket(row),
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
    *,
    preserve_existing_summary: bool = False,
) -> dict[str, str]:
    template_path = registry_dir / "analytical_footprint_review_template.jsonl"
    summary_path = registry_dir / "analytical_footprint_review_summary.json"
    taxonomy_path = registry_dir / "analytical_footprint_error_taxonomy.json"
    review_rows = build_analytical_footprint_review_rows(
        footprint_rows,
        existing_template_path=template_path,
    )
    summary = build_analytical_footprint_review_summary(review_rows)
    taxonomy = build_analytical_footprint_error_taxonomy()
    preserve_summary = preserve_existing_summary and summary_path.exists() and not review_rows
    if preserve_summary:
        summary_output = {"path": summary_path}
    else:
        summary_output = _write_json(summary_path, summary)
    if preserve_existing_summary and taxonomy_path.exists():
        taxonomy_output = {"path": taxonomy_path}
    else:
        taxonomy_output = _write_json(taxonomy_path, taxonomy)
    return {
        "analytical_footprint_review_template": str(
            _write_jsonl(template_path, review_rows)["path"]
        ),
        "analytical_footprint_review_summary": str(
            summary_output["path"]
        ),
        "analytical_footprint_error_taxonomy": str(
            taxonomy_output["path"]
        ),
    }


def _footprint_review_pending_required_fields(
    review_rows: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in review_rows:
        for field in ANALYTICAL_FOOTPRINT_REVIEW_BOOLEAN_FIELDS:
            if not isinstance(row.get(field), bool):
                counts[field] = counts.get(field, 0) + 1
        for field in ("reviewer", "review_date", "review_notes"):
            if not str(row.get(field) or "").strip():
                counts[field] = counts.get(field, 0) + 1
    return dict(sorted(counts.items()))


def prepare_analytical_footprint_review_import(
    root: str | Path,
    output_path: str | Path = ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH,
    *,
    reviewer: str = "",
    review_date: str = "",
    limit: int | None = None,
    offset: int = 0,
    overwrite: bool = False,
) -> AnalyticalFootprintReviewPrepareReport:
    root_path = Path(root)
    target_path = root_path / ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH
    resolved_output_path = Path(output_path)
    if not resolved_output_path.is_absolute():
        resolved_output_path = root_path / resolved_output_path
    target_rows_raw, target_parse_blockers = load_jsonl_with_errors(
        target_path,
        label="analytical footprint target review",
    )
    target_rows, invalid_target_rows = _split_mapping_rows(target_rows_raw)
    blockers: list[str] = []
    if not target_rows_raw:
        blockers.append("analytical footprint review template is empty")
    if invalid_target_rows:
        blockers.append(
            "analytical footprint target review row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in invalid_target_rows)
        )
    blockers.extend(target_parse_blockers)
    if resolved_output_path.exists() and not overwrite:
        blockers.append(f"output_path already exists: {resolved_output_path}")
    offset_value = max(0, int(offset))
    limit_value = None if limit is None else max(0, int(limit))
    if limit_value is None:
        selected_target_rows = target_rows[offset_value:] if offset_value else target_rows
    else:
        selected_target_rows = target_rows[offset_value : offset_value + limit_value]
    scaffold_rows: list[dict[str, Any]] = []
    for row in selected_target_rows:
        scaffold = dict(row)
        if reviewer:
            scaffold["reviewer"] = reviewer
        if review_date:
            scaffold["review_date"] = review_date
        forbidden_paths = manual_review_forbidden_field_paths(scaffold)
        if forbidden_paths:
            blockers.append(
                "analytical footprint review scaffold contains forbidden fields: "
                + ", ".join(forbidden_paths)
            )
        scaffold_rows.append(scaffold)
    if not blockers:
        _write_jsonl(resolved_output_path, scaffold_rows)
    complete_rows = sum(1 for row in scaffold_rows if _footprint_review_row_complete(row))
    report = AnalyticalFootprintReviewPrepareReport(
        report_id="RKE-REPORT-INTELLIGENCE-FOOTPRINT-REVIEW-PREPARE-REPORT",
        target_path=ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
        output_path=str(resolved_output_path),
        accepted=not blockers,
        overwrite=overwrite,
        requested_limit=limit_value,
        requested_offset=offset_value,
        output_rows=len(scaffold_rows),
        complete_rows=complete_rows,
        pending_rows=len(scaffold_rows) - complete_rows,
        pending_required_fields=_footprint_review_pending_required_fields(
            scaffold_rows
        ),
        blockers=tuple(blockers),
    )
    return report


def _review_assist_preview(value: Any, *, max_chars: int = 96) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _review_assist_preview_list(
    value: Any,
    *,
    max_items: int = 3,
    max_chars: int = 96,
) -> tuple[str, ...]:
    return tuple(
        _review_assist_preview(item, max_chars=max_chars)
        for item in _ensure_list(value)[:max_items]
        if str(item or "").strip()
    )


def _markdown_table_cell(value: Any, *, max_chars: int = 96) -> str:
    if isinstance(value, Mapping):
        text = json.dumps(dict(value), ensure_ascii=False, sort_keys=True)
    elif isinstance(value, (list, tuple, set)):
        text = ", ".join(str(item) for item in value)
    else:
        text = str(value or "")
    return _review_assist_preview(text, max_chars=max_chars).replace("|", "\\|") or "-"


def _footprint_review_assist_row(index: int, row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "assist_kind": "analytical_footprint_review_assist_not_import",
        "not_apply_footprint_review_input": True,
        "index": index,
        "footprint_id": str(row.get("footprint_id") or ""),
        "target_row_hash": str(row.get("target_row_hash") or ""),
        "source_id": str(row.get("source_id") or ""),
        "report_id": str(row.get("report_id") or ""),
        "sector": str(row.get("sector") or ""),
        "extraction_type": str(row.get("extraction_type") or ""),
        "topic_preview": _review_assist_preview(row.get("topic_preview"), max_chars=96),
        "indicator_mentions_preview": _review_assist_preview_list(
            row.get("indicator_mentions_review_preview"),
            max_items=3,
            max_chars=80,
        ),
        "analysis_patterns_preview": _review_assist_preview_list(
            row.get("analysis_patterns_review_preview"),
            max_items=3,
            max_chars=80,
        ),
        "target_entity_candidates": tuple(
            _review_assist_preview(item, max_chars=48)
            for item in _ensure_list(row.get("target_entity_candidates"))[:5]
            if str(item or "").strip()
        ),
        "target_agent_candidates": tuple(
            _review_assist_preview(item, max_chars=48)
            for item in _ensure_list(row.get("target_agent_candidates"))[:5]
            if str(item or "").strip()
        ),
        "source_span_count": len(_ensure_list(row.get("source_span_ids"))),
        "review_context_ref": str(row.get("review_context_ref") or ""),
        "target_review_path": ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
        "reviewed_import_path": ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH,
        "human_required_fields": (
            *ANALYTICAL_FOOTPRINT_REVIEW_REQUIRED_FIELDS,
            "manual_error_tags",
        ),
        "human_review_required": True,
    }


def build_analytical_footprint_review_assist(
    root: str | Path = ".",
) -> tuple[AnalyticalFootprintReviewAssistReport, tuple[Mapping[str, Any], ...]]:
    root_path = Path(root)
    target_path = root_path / ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH
    target_rows_raw, target_parse_blockers = load_jsonl_with_errors(
        target_path,
        label="analytical footprint target review",
    )
    target_rows, invalid_target_rows = _split_mapping_rows(target_rows_raw)
    pending_rows = [row for row in target_rows if not _footprint_review_row_complete(row)]
    assist_rows = tuple(
        _footprint_review_assist_row(index, row)
        for index, row in enumerate(pending_rows, 1)
    )
    blockers: list[str] = [*target_parse_blockers]
    if invalid_target_rows:
        blockers.append(
            "analytical footprint target review row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in invalid_target_rows)
        )
    if not target_rows_raw:
        blockers.append("analytical footprint review template is empty")
    elif not target_rows:
        blockers.append("analytical footprint review template has no valid rows")
    return (
        AnalyticalFootprintReviewAssistReport(
            report_id="RKE-REPORT-INTELLIGENCE-FOOTPRINT-REVIEW-ASSIST",
            target_path=ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
            reviewed_import_path=ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH,
            jsonl_path=ANALYTICAL_FOOTPRINT_REVIEW_ASSIST_JSONL_PATH,
            markdown_path=ANALYTICAL_FOOTPRINT_REVIEW_WORKBOOK_MD_PATH,
            row_count=len(assist_rows),
            pending_rows=len(pending_rows),
            blockers=tuple(blockers),
        ),
        assist_rows,
    )


def render_analytical_footprint_review_workbook_markdown(
    report: AnalyticalFootprintReviewAssistReport,
    rows: Sequence[Mapping[str, Any]],
) -> str:
    lines = [
        "# RKE Analytical Footprint Review Workbook",
        "",
        f"- Assist ID: {report.report_id}",
        f"- Pending rows: {report.pending_rows}",
        f"- Review template: `{report.target_path}`",
        f"- Reviewed import target: `{report.reviewed_import_path}`",
        f"- JSONL assist: `{report.jsonl_path}`",
        "",
        "This workbook is private review assistance only. It is not an import file and does not satisfy the analytical-footprint review gate.",
        "Fill reviewer decisions only in the reviewed JSONL scratch file, then dry-run `mosaic-rke apply-footprint-review`.",
        "",
    ]
    if report.blockers:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {blocker}" for blocker in report.blockers)
        lines.append("")
    lines.extend(
        [
            "## Pending Footprints",
            "",
            (
                "| # | footprint_id | target_hash | source_id | sector | type | "
                "source_spans | topic | indicators | analysis_patterns | entities | agents |"
            ),
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown_table_cell(row.get("index"), max_chars=12),
                    _markdown_table_cell(row.get("footprint_id"), max_chars=48),
                    _markdown_table_cell(row.get("target_row_hash"), max_chars=24),
                    _markdown_table_cell(row.get("source_id"), max_chars=48),
                    _markdown_table_cell(row.get("sector"), max_chars=32),
                    _markdown_table_cell(row.get("extraction_type"), max_chars=24),
                    _markdown_table_cell(row.get("source_span_count"), max_chars=12),
                    _markdown_table_cell(row.get("topic_preview"), max_chars=96),
                    _markdown_table_cell(row.get("indicator_mentions_preview"), max_chars=96),
                    _markdown_table_cell(row.get("analysis_patterns_preview"), max_chars=96),
                    _markdown_table_cell(row.get("target_entity_candidates"), max_chars=72),
                    _markdown_table_cell(row.get("target_agent_candidates"), max_chars=72),
                )
            )
            + " |"
        )
    return "\n".join(lines)


def write_analytical_footprint_review_assist(
    root: str | Path = ".",
) -> AnalyticalFootprintReviewAssistReport:
    root_path = Path(root)
    report, rows = build_analytical_footprint_review_assist(root_path)
    _write_jsonl(root_path / ANALYTICAL_FOOTPRINT_REVIEW_ASSIST_JSONL_PATH, rows)
    markdown_path = root_path / ANALYTICAL_FOOTPRINT_REVIEW_WORKBOOK_MD_PATH
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(
        render_analytical_footprint_review_workbook_markdown(report, rows) + "\n",
        encoding="utf-8",
    )
    return report


def _footprint_review_priority_score(row: Mapping[str, Any]) -> int:
    score = 0
    indicator_mentions = _ensure_list(row.get("indicator_mentions_review_preview"))
    analysis_patterns = _ensure_list(row.get("analysis_patterns_review_preview"))
    if not indicator_mentions:
        score += 3
    if len(analysis_patterns) >= 3:
        score += 2
    if not _ensure_list(row.get("target_entity_candidates")):
        score += 2
    if not _ensure_list(row.get("target_agent_candidates")):
        score += 1
    if len(_ensure_list(row.get("source_span_ids"))) > 3:
        score += 1
    return score


def _footprint_review_evidence_terms(row: Mapping[str, Any]) -> tuple[str, ...]:
    raw_terms: list[str] = []
    for value in (
        row.get("sector"),
        row.get("topic_preview"),
        *_ensure_list(row.get("analysis_patterns_review_preview")),
        *_ensure_list(row.get("indicator_mentions_review_preview")),
        *_ensure_list(row.get("target_entity_candidates")),
    ):
        text = str(value or "").strip()
        if not text:
            continue
        raw_terms.append(text)
        raw_terms.extend(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9+\-/ ]{2,}", text))
    raw_terms.extend(
        [
            "营收",
            "归母净利润",
            "毛利率",
            "净利率",
            "同比",
            "环比",
            "销售额",
            "销量",
            "均价",
            "价格",
            "市场",
            "行业",
            "需求",
            "供给",
            "产量",
            "库存",
            "利润",
            "估值",
            "PE",
            "ROE",
            "PMI",
            "政策",
            "产业链",
            "竞争",
            "风险",
        ]
    )
    seen: list[str] = []
    for term in raw_terms:
        normalized = " ".join(str(term or "").split())
        if not normalized or normalized in seen or len(normalized) > 96:
            continue
        seen.append(normalized)
    return tuple(seen)


def _footprint_review_evidence_snippets(
    markdown_text: str,
    terms: Sequence[str],
    *,
    max_snippets: int = 2,
    max_chars: int = 900,
) -> tuple[dict[str, Any], ...]:
    snippets: list[dict[str, Any]] = []
    used_offsets: list[int] = []
    for term in terms:
        match = re.search(re.escape(term), markdown_text, re.IGNORECASE)
        if match is None:
            continue
        offset = int(match.start())
        if any(abs(offset - used) < max_chars for used in used_offsets):
            continue
        start = max(0, offset - max_chars // 3)
        end = min(len(markdown_text), offset + max_chars)
        snippets.append(
            {
                "matched_term": term,
                "start_char": start,
                "end_char": end,
                "snippet": " ".join(markdown_text[start:end].split()),
            }
        )
        used_offsets.append(offset)
        if len(snippets) >= max_snippets:
            break
    if not snippets and markdown_text:
        snippets.append(
            {
                "matched_term": "document_head",
                "start_char": 0,
                "end_char": min(len(markdown_text), max_chars),
                "snippet": " ".join(markdown_text[:max_chars].split()),
            }
        )
    return tuple(snippets)


def _footprint_review_metric_mapping_suggestion(row: Mapping[str, Any]) -> bool:
    return bool(_ensure_list(row.get("indicator_mentions_review_preview")))


FOOTPRINT_REVIEW_INDICATOR_SUGGESTION_RULES: tuple[
    tuple[str, Mapping[str, str]], ...
] = (
    (
        r"earnings|盈利预测|财务预测|业绩|利润|profit",
        {
            "indicator_text": "forecast_net_profit_or_eps",
            "canonical_metric_candidate": "forecast_net_profit",
            "data_source_mentioned": "report_financial_forecast_or_company_financials",
            "frequency": "annual_or_quarterly",
            "transformation": "growth_rate_or_forecast_revision",
            "role_in_argument": "earnings_forecast_metric",
            "confidence": "medium",
        },
    ),
    (
        r"revenue|营收|收入|sales|销售额|销量|sell-through|transaction volume|成交|需求|market[_\s-]*sizing",
        {
            "indicator_text": "revenue_sales_or_demand_growth",
            "canonical_metric_candidate": "demand_or_revenue_growth",
            "data_source_mentioned": "company_financials_or_industry_operation_data",
            "frequency": "monthly_or_quarterly",
            "transformation": "growth_rate",
            "role_in_argument": "demand_growth_proxy",
            "confidence": "medium",
        },
    ),
    (
        r"valuation|估值|pe\b|pb\b|相对估值|目标价|multiple",
        {
            "indicator_text": "valuation_multiple_or_target_price",
            "canonical_metric_candidate": "valuation_multiple",
            "data_source_mentioned": "market_valuation_data_or_report_valuation_model",
            "frequency": "daily_or_point_in_time",
            "transformation": "valuation_ratio_or_model_output",
            "role_in_argument": "valuation_proxy",
            "confidence": "medium",
        },
    ),
    (
        r"margin|毛利率|净利率|盈利能力",
        {
            "indicator_text": "gross_margin_or_net_margin",
            "canonical_metric_candidate": "margin_profitability",
            "data_source_mentioned": "company_financials_or_report_forecast",
            "frequency": "quarterly_or_annual",
            "transformation": "level_or_change",
            "role_in_argument": "profitability_metric",
            "confidence": "medium",
        },
    ),
    (
        r"supply|供给|供需|capacity|产能|库存|inventory|价格|price|commodity|uranium|铜|铝|锂|光伏",
        {
            "indicator_text": "commodity_price_supply_demand_inventory",
            "canonical_metric_candidate": "commodity_price_cycle",
            "data_source_mentioned": "commodity_price_supply_demand_inventory_data",
            "frequency": "daily_or_weekly_or_monthly",
            "transformation": "price_return_or_inventory_change",
            "role_in_argument": "supply_demand_cycle_proxy",
            "confidence": "medium",
        },
    ),
    (
        r"policy|政策|regulat|监管|利率|rate|liquidity|流动性|credit|融资|capital",
        {
            "indicator_text": "policy_liquidity_credit_condition",
            "canonical_metric_candidate": "liquidity_credit_condition",
            "data_source_mentioned": "policy_announcement_or_money_credit_data",
            "frequency": "event_driven_or_monthly",
            "transformation": "event_flag_or_growth_rate",
            "role_in_argument": "policy_or_liquidity_transmission_proxy",
            "confidence": "low",
        },
    ),
    (
        r"return|performance|涨跌幅|相对表现|ranking|指数|etf|benchmark",
        {
            "indicator_text": "stock_or_sector_relative_return",
            "canonical_metric_candidate": "relative_alpha",
            "data_source_mentioned": "stock_etf_or_index_price",
            "frequency": "daily",
            "transformation": "forward_return_minus_benchmark",
            "role_in_argument": "market_outcome_proxy",
            "confidence": "medium",
        },
    ),
    (
        r"cash[_\s-]*flow|现金流",
        {
            "indicator_text": "operating_cash_flow",
            "canonical_metric_candidate": "operating_cash_flow",
            "data_source_mentioned": "company_cash_flow_statement",
            "frequency": "quarterly_or_annual",
            "transformation": "level_or_growth",
            "role_in_argument": "cash_generation_metric",
            "confidence": "medium",
        },
    ),
    (
        r"capex|r&d|研发|投产|实验室|产线|扩产",
        {
            "indicator_text": "capex_rd_or_capacity_release",
            "canonical_metric_candidate": "capex_rd_capacity_release",
            "data_source_mentioned": "company_disclosure_or_financials",
            "frequency": "quarterly_or_event_driven",
            "transformation": "level_or_milestone_event",
            "role_in_argument": "capacity_or_innovation_execution_metric",
            "confidence": "low",
        },
    ),
)


def _footprint_review_indicator_suggestion_context(row: Mapping[str, Any]) -> str:
    values: list[str] = []
    for value in (
        row.get("sector"),
        row.get("topic_preview"),
        *_ensure_list(row.get("analysis_patterns_review_preview")),
        *_ensure_list(row.get("target_entity_candidates")),
        *_ensure_list(row.get("target_agent_candidates")),
    ):
        text = str(value or "").strip()
        if text:
            values.append(text)
    return " ".join(values)


def _footprint_review_inferred_indicator_suggestions(
    row: Mapping[str, Any],
    *,
    max_items: int = 5,
) -> tuple[dict[str, Any], ...]:
    if _ensure_list(row.get("indicator_mentions_review_preview")):
        return ()
    context = _footprint_review_indicator_suggestion_context(row)
    if not context:
        return ()
    suggestions: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for pattern, metadata in FOOTPRINT_REVIEW_INDICATOR_SUGGESTION_RULES:
        if not re.search(pattern, context, flags=re.IGNORECASE):
            continue
        canonical = str(metadata.get("canonical_metric_candidate") or "unknown")
        indicator_text = str(metadata.get("indicator_text") or canonical)
        key = (indicator_text, canonical)
        if key in seen:
            continue
        seen.add(key)
        suggestions.append(
            {
                "indicator_text": indicator_text,
                "canonical_metric_candidate": canonical,
                "data_source_mentioned": str(
                    metadata.get("data_source_mentioned") or "unknown"
                ),
                "frequency": str(metadata.get("frequency") or "unknown"),
                "lookback_window": {},
                "transformation": str(metadata.get("transformation") or "unknown"),
                "role_in_argument": str(metadata.get("role_in_argument") or "unknown"),
                "source_grounded": False,
                "inference_source": "review_evidence_context_rule",
                "confidence": str(metadata.get("confidence") or "low"),
                "review_note": (
                    "Suggested from footprint topic/pattern metadata only; reviewer must "
                    "confirm against local markdown before importing a decision."
                ),
            }
        )
        if len(suggestions) >= max_items:
            break
    return tuple(suggestions)


def _is_boilerplate_risk_warning_text(text: str) -> bool:
    stripped = text.strip()
    if FORECAST_CLAIM_RISK_WARNING_PREFIX_RE.match(stripped):
        return True
    return len(stripped) <= 80 and bool(GENERIC_RISK_WARNING_ENUM_RE.match(stripped))


def _is_boilerplate_risk_footprint(row: Mapping[str, Any]) -> bool:
    texts = [
        str(row.get("topic_preview") or ""),
        *[str(item or "") for item in _ensure_list(row.get("analysis_patterns_review_preview"))],
        *[str(item or "") for item in _ensure_list(row.get("target_entity_candidates"))],
    ]
    normalized = " ".join(text for text in texts if text.strip())
    if any(_is_boilerplate_risk_warning_text(text) for text in texts):
        return True
    risk_title = any(
        text.strip() in {"风险提示", "行业风险提示", "宏观经济风险提示", "投资建议与风险提示"}
        or text.strip().endswith("风险提示")
        for text in texts
    )
    risk_workflow_only = (
        risk_title
        and any(term in normalized for term in ("风险因素", "风险列举", "风险识别", "风险管理"))
        and not any(
            term in normalized
            for term in (
                "供需",
                "景气",
                "盈利",
                "估值",
                "目标价",
                "投资逻辑",
                "需求展望",
                "政策影响",
                "产业链供需",
            )
        )
    )
    return risk_workflow_only


def _footprint_review_evidence_row(
    index: int,
    row: Mapping[str, Any],
    *,
    metadata_by_source: Mapping[str, Mapping[str, Any]],
    root_path: Path,
) -> dict[str, Any]:
    source_id = str(row.get("source_id") or "")
    metadata = metadata_by_source.get(source_id, {})
    markdown_info = _ensure_mapping(metadata.get("markdown"))
    markdown_path_text = str(markdown_info.get("path") or "")
    markdown_path = Path(markdown_path_text)
    if markdown_path_text and not markdown_path.is_absolute():
        markdown_path = root_path / markdown_path
    markdown_exists = bool(markdown_path_text and markdown_path.exists())
    markdown_text = markdown_path.read_text(encoding="utf-8", errors="ignore") if markdown_exists else ""
    terms = _footprint_review_evidence_terms(row)
    snippets = _footprint_review_evidence_snippets(markdown_text, terms)
    has_span_evidence = bool(snippets and markdown_exists)
    has_patterns = bool(_ensure_list(row.get("analysis_patterns_review_preview")))
    has_indicators = _footprint_review_metric_mapping_suggestion(row)
    boilerplate_risk_footprint = _is_boilerplate_risk_footprint(row)
    inferred_indicator_suggestions = (
        ()
        if boilerplate_risk_footprint
        else _footprint_review_inferred_indicator_suggestions(row)
    )
    suggested_decision = {
        "footprint_correct": False if boilerplate_risk_footprint else (True if has_span_evidence and has_patterns else None),
        "source_span_supports_footprint": True if has_span_evidence else None,
        "metric_mapping_correct": False if boilerplate_risk_footprint else has_indicators,
        "inferred_steps_tagged_correctly": False if boilerplate_risk_footprint else (True if has_patterns else None),
        "unknowns_used_when_uncertain": True,
        "no_proprietary_text_leakage": True,
    }
    suggested_tags: list[str] = []
    suggested_rationales: list[dict[str, Any]] = []
    if boilerplate_risk_footprint:
        suggested_tags.append("boilerplate_risk_warning_footprint")
        suggested_rationales.append(
            {
                "field": "footprint_correct",
                "suggested_value": False,
                "reason": "footprint appears to be a generic risk-warning workflow rather than reusable analytical logic",
                "requires_human_confirmation": True,
            }
        )
    if not markdown_exists:
        suggested_tags.append("markdown_missing")
        suggested_rationales.append(
            {
                "field": "source_span_supports_footprint",
                "suggested_value": None,
                "reason": "local markdown evidence is missing, so span support cannot be verified",
                "requires_human_confirmation": True,
            }
        )
    elif has_span_evidence:
        suggested_rationales.append(
            {
                "field": "source_span_supports_footprint",
                "suggested_value": True,
                "reason": "local markdown snippets were found for the footprint topic, indicators, patterns, or target entities",
                "requires_human_confirmation": True,
            }
        )
    else:
        suggested_rationales.append(
            {
                "field": "source_span_supports_footprint",
                "suggested_value": None,
                "reason": "local markdown exists but no matching snippet was found for the review terms",
                "requires_human_confirmation": True,
            }
        )
    if not has_indicators:
        suggested_tags.append("metric_mapping_missing")
        suggested_rationales.append(
            {
                "field": "metric_mapping_correct",
                "suggested_value": False if boilerplate_risk_footprint else has_indicators,
                "reason": "extracted footprint has no source-grounded indicator mentions",
                "requires_human_confirmation": True,
            }
        )
    if inferred_indicator_suggestions:
        suggested_tags.append("metric_mapping_inference_available")
        suggested_rationales.append(
            {
                "field": "metric_mapping_correct",
                "suggested_value": False,
                "reason": "context-derived indicator candidates are available, but they are review aids and not source-grounded mappings",
                "requires_human_confirmation": True,
            }
        )
    if not has_patterns:
        suggested_tags.append("analysis_pattern_missing")
        suggested_rationales.append(
            {
                "field": "inferred_steps_tagged_correctly",
                "suggested_value": None if not boilerplate_risk_footprint else False,
                "reason": "extracted footprint has no analysis pattern steps to review",
                "requires_human_confirmation": True,
            }
        )
    elif not boilerplate_risk_footprint:
        suggested_rationales.append(
            {
                "field": "inferred_steps_tagged_correctly",
                "suggested_value": True,
                "reason": "analysis patterns are present; reviewer should verify the steps match local evidence",
                "requires_human_confirmation": True,
            }
        )
    if not has_span_evidence:
        suggested_tags.append("source_span_evidence_unverified")
    if not boilerplate_risk_footprint and has_span_evidence and has_patterns:
        suggested_rationales.append(
            {
                "field": "footprint_correct",
                "suggested_value": True,
                "reason": "footprint has local evidence snippets and analysis patterns; reviewer should confirm it is meaningful analytical logic",
                "requires_human_confirmation": True,
            }
        )
    suggested_rationales.append(
        {
            "field": "unknowns_used_when_uncertain",
            "suggested_value": True,
            "reason": "draft suggestion preserves null/unknown decisions when metric, span, or pattern support is not proven",
            "requires_human_confirmation": True,
        }
    )
    suggested_rationales.append(
        {
            "field": "no_proprietary_text_leakage",
            "suggested_value": True,
            "reason": "evidence row is private and not an import row; reviewer still must keep proprietary snippets out of reviewed imports",
            "requires_human_confirmation": True,
        }
    )
    return {
        "evidence_kind": "analytical_footprint_review_evidence_not_import",
        "not_apply_footprint_review_input": True,
        "human_review_required": True,
        "index": index,
        "priority_score": _footprint_review_priority_score(row),
        "footprint_id": str(row.get("footprint_id") or ""),
        "target_row_hash": str(row.get("target_row_hash") or ""),
        "source_id": source_id,
        "report_id": str(row.get("report_id") or ""),
        "sector": str(row.get("sector") or ""),
        "topic_preview": _review_assist_preview(row.get("topic_preview"), max_chars=160),
        "indicator_mentions_preview": _review_assist_preview_list(
            row.get("indicator_mentions_review_preview"),
            max_items=6,
            max_chars=120,
        ),
        "inferred_indicator_suggestions": inferred_indicator_suggestions,
        "analysis_patterns_preview": _review_assist_preview_list(
            row.get("analysis_patterns_review_preview"),
            max_items=6,
            max_chars=120,
        ),
        "target_entity_candidates": tuple(
            _review_assist_preview(item, max_chars=80)
            for item in _ensure_list(row.get("target_entity_candidates"))[:8]
            if str(item or "").strip()
        ),
        "metadata_title_preview": _review_assist_preview(metadata.get("title"), max_chars=160),
        "markdown_path": markdown_path_text,
        "markdown_exists": markdown_exists,
        "evidence_terms": terms[:16],
        "evidence_snippets": snippets,
        "suggested_review_decision": suggested_decision,
        "suggested_review_rationales": tuple(suggested_rationales),
        "suggested_manual_error_tags": tuple(suggested_tags),
        "suggested_review_notes": (
            "Review against local markdown evidence. Draft suggestion only; copy decisions "
            "to analytical_footprint_reviewed.jsonl only after human approval."
        ),
        "reviewed_import_path": ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH,
    }


def build_analytical_footprint_review_evidence(
    root: str | Path = ".",
    *,
    limit: int = 25,
    offset: int = 0,
    review_input_path: str | Path | None = None,
) -> tuple[AnalyticalFootprintReviewEvidenceReport, tuple[Mapping[str, Any], ...]]:
    root_path = Path(root)
    target_path = root_path / ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH
    metadata_path = root_path / "registry/report_intelligence/report_metadata.jsonl"
    target_rows_raw, target_parse_blockers = load_jsonl_with_errors(
        target_path,
        label="analytical footprint target review",
    )
    metadata_rows_raw, metadata_parse_blockers = load_jsonl_with_errors(
        metadata_path,
        label="analytical footprint evidence report metadata",
    )
    target_rows, invalid_target_rows = _split_mapping_rows(target_rows_raw)
    metadata_rows, invalid_metadata_rows = _split_mapping_rows(metadata_rows_raw)
    metadata_by_source = {
        str(row.get("source_id") or ""): row
        for row in metadata_rows
        if str(row.get("source_id") or "").strip()
    }
    pending_rows = [row for row in target_rows if not _footprint_review_row_complete(row)]
    blockers: list[str] = [*target_parse_blockers, *metadata_parse_blockers]
    selection_source = "priority_sorted_pending"
    review_input_text = ""
    target_by_id = {
        str(row.get("footprint_id") or ""): row
        for row in target_rows
        if str(row.get("footprint_id") or "").strip()
    }
    if review_input_path is not None:
        selection_source = "review_input"
        review_input = Path(review_input_path)
        review_input_text = str(review_input)
        input_rows_raw, input_parse_blockers = load_jsonl_with_errors(
            root_path / review_input,
            label="analytical footprint review input",
        )
        input_rows, invalid_input_rows = _split_mapping_rows(input_rows_raw)
        blockers.extend(input_parse_blockers)
        if invalid_input_rows:
            blockers.append(
                "analytical footprint review input row must be object at row(s): "
                + ", ".join(str(row_number) for row_number in invalid_input_rows)
            )
        if not input_rows_raw:
            blockers.append("analytical footprint review input is missing or empty")
        selected_rows: list[Mapping[str, Any]] = []
        seen_footprint_ids: set[str] = set()
        for row_index, input_row in enumerate(input_rows, 1):
            footprint_id = str(input_row.get("footprint_id") or "").strip()
            if not footprint_id:
                blockers.append(
                    f"analytical footprint review input row {row_index}.footprint_id: required"
                )
                continue
            if footprint_id in seen_footprint_ids:
                blockers.append(
                    "analytical footprint review input row "
                    f"{row_index}.footprint_id: duplicate {footprint_id}"
                )
                continue
            seen_footprint_ids.add(footprint_id)
            target_row = target_by_id.get(footprint_id)
            if target_row is None:
                blockers.append(
                    "analytical footprint review input row "
                    f"{row_index}.footprint_id: no matching target review row"
                )
                continue
            input_hash = str(input_row.get("target_row_hash") or "").strip()
            target_hash = str(target_row.get("target_row_hash") or "").strip()
            if input_hash and target_hash and input_hash != target_hash:
                blockers.append(
                    "analytical footprint review input row "
                    f"{row_index}.target_row_hash: does not match target review row"
                )
            selected_rows.append(target_row)
        prioritized_rows = tuple(enumerate(selected_rows, 1))
    else:
        prioritized_rows = sorted(
            enumerate(pending_rows, 1),
            key=lambda item: (-_footprint_review_priority_score(item[1]), item[0]),
        )[max(0, int(offset)) : max(0, int(offset)) + max(0, int(limit))]
    evidence_rows = tuple(
        _footprint_review_evidence_row(
            index,
            row,
            metadata_by_source=metadata_by_source,
            root_path=root_path,
        )
        for index, row in prioritized_rows
    )
    if invalid_target_rows:
        blockers.append(
            "analytical footprint target review row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in invalid_target_rows)
        )
    if invalid_metadata_rows:
        blockers.append(
            "report metadata row must be object at row(s): "
            + ", ".join(str(row_number) for row_number in invalid_metadata_rows)
        )
    if not target_rows:
        blockers.append("analytical footprint review template has no valid rows")
    if not metadata_rows:
        blockers.append("report metadata has no valid rows")
    missing_markdown_rows = sum(1 for row in evidence_rows if not row.get("markdown_exists"))
    return (
        AnalyticalFootprintReviewEvidenceReport(
            report_id="RKE-REPORT-INTELLIGENCE-FOOTPRINT-REVIEW-EVIDENCE",
            target_path=ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
            reviewed_import_path=ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH,
            jsonl_path=ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_JSONL_PATH,
            markdown_path=ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_MD_PATH,
            requested_limit=max(0, int(limit)),
            requested_offset=max(0, int(offset)),
            row_count=len(evidence_rows),
            evidence_rows=sum(1 for row in evidence_rows if row.get("evidence_snippets")),
            missing_markdown_rows=missing_markdown_rows,
            blockers=tuple(blockers),
            selection_source=selection_source,
            review_input_path=review_input_text,
        ),
        evidence_rows,
    )


def render_analytical_footprint_review_evidence_markdown(
    report: AnalyticalFootprintReviewEvidenceReport,
    rows: Sequence[Mapping[str, Any]],
) -> str:
    suggested_tag_counts = Counter(
        str(tag)
        for row in rows
        for tag in _ensure_list(row.get("suggested_manual_error_tags"))
        if str(tag).strip()
    )
    sector_counts = Counter(
        str(row.get("sector") or "unknown") for row in rows if str(row.get("sector") or "").strip()
    )
    decision_counts: dict[str, Counter[str]] = {
        field: Counter()
        for field in (
            "footprint_correct",
            "source_span_supports_footprint",
            "metric_mapping_correct",
            "inferred_steps_tagged_correctly",
            "unknowns_used_when_uncertain",
            "no_proprietary_text_leakage",
        )
    }
    for row in rows:
        decision = row.get("suggested_review_decision")
        decision_map = _ensure_mapping(decision)
        for field, counts in decision_counts.items():
            value = decision_map.get(field)
            if value is True:
                counts["true"] += 1
            elif value is False:
                counts["false"] += 1
            else:
                counts["null"] += 1
    lines = [
        "# RKE Analytical Footprint Review Evidence Draft",
        "",
        f"- Evidence ID: {report.report_id}",
        f"- Rows: {report.row_count}",
        f"- Review template: `{report.target_path}`",
        f"- Reviewed import target: `{report.reviewed_import_path}`",
        "",
        "This private file contains local source snippets and machine suggestions for human review. It is not an import file.",
        "Do not commit this file. Confirm decisions before copying them into the reviewed JSONL scratch file.",
        "",
    ]
    lines.extend(
        [
            "## Batch Triage Summary",
            "",
            "- Suggested tag counts: "
            + _markdown_table_cell(
                dict(sorted(suggested_tag_counts.items())),
                max_chars=500,
            ),
            "- Sector counts: "
            + _markdown_table_cell(dict(sorted(sector_counts.items())), max_chars=500),
            "- Suggested decision counts: "
            + _markdown_table_cell(
                {field: dict(counts) for field, counts in decision_counts.items()},
                max_chars=900,
            ),
            "",
        ]
    )
    if report.blockers:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {blocker}" for blocker in report.blockers)
        lines.append("")
    for row in rows:
        lines.extend(
            [
                f"## {row.get('index')}. {row.get('footprint_id')}",
                "",
                f"- Source: `{row.get('source_id')}`",
                f"- Sector: {row.get('sector') or '-'}",
                f"- Topic: {row.get('topic_preview') or '-'}",
                f"- Priority score: {row.get('priority_score')}",
                f"- Suggested tags: {_markdown_table_cell(row.get('suggested_manual_error_tags'), max_chars=200)}",
                "",
                "Suggested decision:",
                "",
                "```json",
                json.dumps(row.get("suggested_review_decision"), ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
        rationales = _ensure_list(row.get("suggested_review_rationales"))
        if rationales:
            lines.extend(
                [
                    "Suggested decision rationales:",
                    "",
                    "```json",
                    json.dumps(rationales, ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )
        indicator_suggestions = _ensure_list(row.get("inferred_indicator_suggestions"))
        if indicator_suggestions:
            lines.extend(
                [
                    "Suggested indicator mapping candidates:",
                    "",
                    "```json",
                    json.dumps(indicator_suggestions, ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )
        lines.extend(["Evidence snippets:", ""])
        snippets = _ensure_list(row.get("evidence_snippets"))
        if not snippets:
            lines.append("- No local markdown evidence snippet found.")
        for snippet in snippets:
            snippet_map = _ensure_mapping(snippet)
            lines.extend(
                [
                    f"- Matched term: `{snippet_map.get('matched_term')}`",
                    "",
                    "> " + _review_assist_preview(snippet_map.get("snippet"), max_chars=900),
                    "",
                ]
            )
    return "\n".join(lines)


def write_analytical_footprint_review_evidence(
    root: str | Path = ".",
    *,
    limit: int = 25,
    offset: int = 0,
    review_input_path: str | Path | None = None,
) -> AnalyticalFootprintReviewEvidenceReport:
    root_path = Path(root)
    report, rows = build_analytical_footprint_review_evidence(
        root_path,
        limit=limit,
        offset=offset,
        review_input_path=review_input_path,
    )
    _write_jsonl(root_path / ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_JSONL_PATH, rows)
    markdown_path = root_path / ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_MD_PATH
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(
        render_analytical_footprint_review_evidence_markdown(report, rows) + "\n",
        encoding="utf-8",
    )
    return report


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
            name = (
                str(pattern).strip()
                if isinstance(pattern, str)
                else _record_text(pattern_map, "pattern_candidate", "name", "pattern")
            )
            if name:
                raw_methods.append(
                    {
                        "name": name,
                        "source_footprint_ids": [footprint.get("footprint_id")],
                        "steps": pattern_map.get("steps") or [name],
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
                "method_pattern_id": _stable_id("METHOD", {"canonical_name": key}),
                "canonical_name": key,
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
            (
                "revenue",
                "net_profit",
                "gross_margin",
                "net_margin",
                "margin",
                "roe",
                "roic",
                "eps",
                "earnings",
                "p/e",
                "p/b",
                "pe_ratio",
                "pb_ratio",
                "ev_ebitda",
                "price_to_book",
                "price_to_earnings",
                "target_price",
                "financial_model",
                "profitability",
                "expense_ratio",
                "yoy_growth",
                "year_over_year",
                "quarter_over_quarter",
                "valuation",
                "营业收入",
                "归母净利润",
                "净利润",
                "毛利率",
                "净利率",
                "市盈率",
                "市净率",
                "每股收益",
                "估值",
            ),
            "exact_match",
            ("tool.get_fundamentals",),
        ),
        (
            (
                "debt_to_asset",
                "asset_liability",
                "current_ratio",
                "book_value",
                "资产负债率",
                "流动比率",
                "每股净资产",
            ),
            "exact_match",
            ("tool.get_balance_sheet",),
        ),
        (
            (
                "cashflow",
                "cash_flow",
                "operating_cash",
                "investing_cash",
                "financing_cash",
                "经营活动现金流",
                "投资活动现金流",
                "筹资活动现金流",
                "现金及现金等价物",
            ),
            "exact_match",
            ("tool.get_cashflow",),
        ),
        (
            (
                "receivable_turnover",
                "inventory_turnover",
                "asset_turnover",
                "应收账款周转率",
                "存货周转率",
                "总资产周转率",
            ),
            "exact_match",
            ("tool.get_fundamentals",),
        ),
        (
            (
                "stock_price",
                "stock_return",
                "benchmark_return",
                "industry_etf_forward_return",
                "sector_index_return",
                "forward_return",
                "target_return",
                "relative_alpha",
                "relative_performance",
                "price_proxy",
                "sector_relative_performance",
                "股价",
                "收益率",
            ),
            "exact_match",
            ("market.price_proxy",),
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


def _tool_gap_resolved_by_existing_coverage(row: Mapping[str, Any]) -> bool:
    metric_name = str(row.get("metric_name") or row.get("metric_candidate_id") or "")
    if not metric_name.strip():
        return False
    coverage = classify_tool_coverage(metric_name)
    return bool(coverage.get("existing_tool_ids")) and str(
        coverage.get("coverage_status") or ""
    ) in {"exact_match", "proxy_available"}


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
        if _tool_gap_resolved_by_existing_coverage(row):
            governed = dict(row)
            governed.update(
                {
                    "priority_bucket": "resolved",
                    "priority_reasons": _merge_unique_values(
                        _ensure_list(row.get("priority_reasons")),
                        ["metric_now_has_existing_tool_coverage"],
                    ),
                    "blocking_issues": [],
                    "owner": str(row.get("owner") or "data_engineering"),
                    "status": "retired",
                }
            )
            governed_rows.append(governed)
            continue
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
    macro_regime_calendar_rows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    gap_counts: dict[str, int] = {}
    unlabelable_gap_counts: dict[str, int] = {}
    test_status_counts: dict[str, int] = {}
    mechanism_channel_counts: dict[str, int] = {}
    mechanism_action_counts: dict[str, int] = {}
    mechanism_impact_variable_counts: dict[str, int] = {}
    mechanism_gap_counts: dict[str, int] = {}
    mechanism_gap_ids: list[str] = []
    macro_regime_counts: dict[str, int] = {}
    source_text_macro_regime_counts: dict[str, int] = {}
    as_of_date_macro_regime_counts: dict[str, int] = {}
    macro_regime_source_counts: dict[str, int] = {}
    industry_cycle_regime_counts: dict[str, int] = {}
    regime_gap_counts: dict[str, int] = {}
    regime_gap_ids: list[str] = []
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
    industry_proxy_pending_ids = [
        str(claim_id)
        for claim_id in _ensure_list(
            industry_proxy.get("pending_future_forecast_claim_ids")
        )
        if str(claim_id).strip()
    ]
    stock_proxy_label_ready_ids = [
        str(claim_id)
        for claim_id in _ensure_list(stock_proxy.get("labelable_forecast_claim_ids"))
        if str(claim_id).strip()
    ]
    stock_proxy_pending_ids = [
        str(claim_id)
        for claim_id in _ensure_list(stock_proxy.get("pending_future_forecast_claim_ids"))
        if str(claim_id).strip()
    ]
    proxy_label_ready_ids = sorted(
        set(industry_proxy_label_ready_ids) | set(stock_proxy_label_ready_ids)
    )
    proxy_label_ready_id_set = set(proxy_label_ready_ids)
    proxy_label_pending_ids = sorted(
        (set(industry_proxy_pending_ids) | set(stock_proxy_pending_ids))
        - proxy_label_ready_id_set
    )
    proxy_label_pending_id_set = set(proxy_label_pending_ids)
    proxy_label_only_ids: list[str] = []
    proxy_label_pending_only_ids: list[str] = []
    forecast_by_id = {
        str(row.get("forecast_claim_id") or ""): row for row in forecast_rows
    }
    for forecast in forecast_rows:
        forecast_claim_id = str(forecast.get("forecast_claim_id") or "")
        extraction_quality = _ensure_mapping(forecast.get("extraction_quality"))
        component_roles = _ensure_mapping(
            extraction_quality.get("claim_component_roles")
        )
        if not component_roles:
            component_roles = _infer_claim_component_roles(
                str(forecast.get("claim_text") or ""),
                target=_ensure_mapping(forecast.get("target")),
                as_of_datetime=(
                    forecast.get("signal_datetime")
                    or forecast.get("publish_date")
                    or ""
                ),
                macro_regime_calendar_rows=macro_regime_calendar_rows,
            )
        for regime_type in _ensure_list(
            component_roles.get("macro_regime_context_types")
        ):
            key = str(regime_type).strip()
            if key:
                macro_regime_counts[key] = macro_regime_counts.get(key, 0) + 1
        for regime_type in _ensure_list(
            component_roles.get("source_text_macro_regime_context_types")
        ):
            key = str(regime_type).strip()
            if key:
                source_text_macro_regime_counts[key] = (
                    source_text_macro_regime_counts.get(key, 0) + 1
                )
                macro_regime_source_counts["report_text"] = (
                    macro_regime_source_counts.get("report_text", 0) + 1
                )
        for regime_type in _ensure_list(
            component_roles.get("as_of_date_macro_regime_context_types")
        ):
            key = str(regime_type).strip()
            if key:
                as_of_date_macro_regime_counts[key] = (
                    as_of_date_macro_regime_counts.get(key, 0) + 1
                )
                macro_regime_source_counts["as_of_date"] = (
                    macro_regime_source_counts.get("as_of_date", 0) + 1
                )
        for regime_type in _ensure_list(
            component_roles.get("industry_cycle_regime_context_types")
        ):
            key = str(regime_type).strip()
            if key:
                industry_cycle_regime_counts[key] = (
                    industry_cycle_regime_counts.get(key, 0) + 1
                )
        regime_gaps: list[str] = []
        if component_roles.get("has_regime_context") is not True:
            if component_roles.get("has_company_capability_or_action") is True:
                regime_gaps.append("company_capability_only_no_regime_context")
            else:
                regime_gaps.append("regime_context_missing")
        elif (
            component_roles.get("has_macro_regime_context") is not True
            and component_roles.get("has_industry_cycle_regime_context") is not True
        ):
            regime_gaps.append("regime_context_unclassified")
        if regime_gaps and forecast_claim_id:
            regime_gap_ids.append(forecast_claim_id)
        for gap in regime_gaps:
            regime_gap_counts[gap] = regime_gap_counts.get(gap, 0) + 1
        mechanism_roles = _ensure_mapping(
            extraction_quality.get("claim_mechanism_roles")
        )
        if not mechanism_roles:
            mechanism_roles = _infer_claim_mechanism_roles(
                str(forecast.get("claim_text") or ""),
                target=_ensure_mapping(forecast.get("target")),
                metric_proxy_mapping=_ensure_list(
                    forecast.get("metric_proxy_mapping")
                ),
            )
        for channel in _ensure_list(mechanism_roles.get("channels")):
            key = str(channel).strip()
            if key:
                mechanism_channel_counts[key] = (
                    mechanism_channel_counts.get(key, 0) + 1
                )
        for action in _ensure_list(mechanism_roles.get("actions")):
            key = str(action).strip()
            if key:
                mechanism_action_counts[key] = mechanism_action_counts.get(key, 0) + 1
        for variable in _ensure_list(mechanism_roles.get("impact_variables")):
            key = str(variable).strip()
            if key:
                mechanism_impact_variable_counts[key] = (
                    mechanism_impact_variable_counts.get(key, 0) + 1
                )
        mechanism_gaps: list[str] = []
        if mechanism_roles.get("has_economic_mechanism") is not True:
            mechanism_gaps.append("economic_mechanism_missing")
        if mechanism_roles.get("mechanism_connects_to_evaluable_impact") is not True:
            mechanism_gaps.append("mechanism_evaluable_impact_missing")
        if mechanism_roles.get("possible_operational_only_mechanism") is True:
            mechanism_gaps.append("possible_operational_only_mechanism")
        if mechanism_gaps and forecast_claim_id:
            mechanism_gap_ids.append(forecast_claim_id)
        for gap in mechanism_gaps:
            mechanism_gap_counts[gap] = mechanism_gap_counts.get(gap, 0) + 1
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
        elif forecast_claim_id in proxy_label_pending_id_set:
            proxy_label_pending_only_ids.append(forecast_claim_id)
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
            if not (
                has_proxy_label_path or forecast_claim_id in proxy_label_pending_id_set
            ):
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
        "proxy_label_pending_count": len(proxy_label_pending_ids),
        "industry_proxy_label_pending_count": len(industry_proxy_pending_ids),
        "stock_proxy_label_pending_count": len(stock_proxy_pending_ids),
        "proxy_label_pending_only_count": len(proxy_label_pending_only_ids),
        "test_status_counts": dict(sorted(test_status_counts.items())),
        "mapping_gap_counts": dict(sorted(gap_counts.items())),
        "unlabelable_mapping_gap_counts": dict(sorted(unlabelable_gap_counts.items())),
        "macro_regime_counts": dict(sorted(macro_regime_counts.items())),
        "source_text_macro_regime_counts": dict(
            sorted(source_text_macro_regime_counts.items())
        ),
        "as_of_date_macro_regime_counts": dict(
            sorted(as_of_date_macro_regime_counts.items())
        ),
        "macro_regime_source_counts": dict(sorted(macro_regime_source_counts.items())),
        "industry_cycle_regime_counts": dict(
            sorted(industry_cycle_regime_counts.items())
        ),
        "regime_gap_counts": dict(sorted(regime_gap_counts.items())),
        "mechanism_channel_counts": dict(sorted(mechanism_channel_counts.items())),
        "mechanism_action_counts": dict(sorted(mechanism_action_counts.items())),
        "mechanism_impact_variable_counts": dict(
            sorted(mechanism_impact_variable_counts.items())
        ),
        "mechanism_gap_counts": dict(sorted(mechanism_gap_counts.items())),
        "ready_forecast_claim_ids": ready_ids,
        "standard_blocked_forecast_claim_ids": standard_blocked_ids,
        "proxy_label_ready_forecast_claim_ids": proxy_label_ready_ids,
        "industry_proxy_label_ready_forecast_claim_ids": industry_proxy_label_ready_ids,
        "stock_proxy_label_ready_forecast_claim_ids": stock_proxy_label_ready_ids,
        "proxy_label_only_ready_forecast_claim_ids": proxy_label_only_ids,
        "proxy_label_pending_forecast_claim_ids": proxy_label_pending_ids,
        "industry_proxy_label_pending_forecast_claim_ids": industry_proxy_pending_ids,
        "stock_proxy_label_pending_forecast_claim_ids": stock_proxy_pending_ids,
        "proxy_label_pending_only_forecast_claim_ids": proxy_label_pending_only_ids,
        "blocked_forecast_claim_ids": blocked_ids,
        "regime_gap_forecast_claim_ids": sorted(set(regime_gap_ids)),
        "mechanism_gap_forecast_claim_ids": sorted(set(mechanism_gap_ids)),
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
        "mechanism_policy": (
            "mechanism roles are diagnostic extraction governance only; regime, "
            "mechanism, company capability, and impact must stay separable before "
            "mechanism-specific prompt evolution or performance attribution"
        ),
        "as_of_date_macro_regime_policy": (
            "macro regime may be supplemented from PIT as_of_datetime using "
            "predefined historical regime windows; report_text and as_of_date "
            "macro regime counts are tracked separately"
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


def _public_qlib_source_label(qlib_dir: str | Path) -> str:
    raw = str(qlib_dir or "").strip()
    normalized = raw.rstrip("/")
    if normalized == DEFAULT_Q_LIB_ETF_PATH:
        return "qlib://cn_etf"
    if normalized == DEFAULT_Q_LIB_STOCK_PATH:
        return "qlib://cn_data"
    name = Path(os.path.expanduser(raw)).name or "custom"
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._-") or "custom"
    return f"qlib://custom/{safe_name}"


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


def _entry_calendar_index(
    calendar: Sequence[str],
    signal_datetime: str,
    *,
    entry_lag_trading_days: int,
) -> int | None:
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
    entry_index = first_strictly_after_signal + max(0, entry_lag_trading_days - 1)
    if entry_index >= len(calendar):
        return None
    return entry_index


def _entry_calendar_date(
    calendar: Sequence[str],
    signal_datetime: str,
    *,
    entry_lag_trading_days: int,
) -> str:
    entry_index = _entry_calendar_index(
        calendar,
        signal_datetime,
        entry_lag_trading_days=entry_lag_trading_days,
    )
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


def _is_explicit_stock_ts_code(value: Any) -> bool:
    text = str(value or "").strip().upper()
    match = re.fullmatch(r"(\d{6})\.(SH|SZ|BJ)", text)
    if not match:
        return False
    code, market = match.groups()
    if market == "SH" and not code.startswith(("60", "68")):
        return False
    if market == "SZ" and not code.startswith(("00", "30")):
        return False
    return market != "BJ" or code.startswith("92")


def _is_explicit_stock_research_report(metadata: Mapping[str, Any]) -> bool:
    return _is_potential_stock_report(metadata) and bool(
        _is_explicit_stock_ts_code(metadata.get("ts_code"))
    )


def _normalize_ts_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    match = re.fullmatch(r"(\d{6})\.(SH|SZ|BJ)", text)
    if not match:
        return ""
    code, market = match.groups()
    if market == "SH" and not code.startswith(("60", "68")):
        return ""
    if market == "SZ" and not code.startswith(("00", "30")):
        return ""
    if market == "BJ" and not code.startswith("92"):
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


def _as_of_date_market_regime_fields(
    signal_datetime: Any,
    *,
    macro_regime_calendar_rows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    regime_types, _sources, details = _as_of_date_macro_regime_context(
        signal_datetime,
        macro_regime_calendar_rows=macro_regime_calendar_rows,
    )
    if not regime_types:
        return {}
    return {
        "market_regime": "|".join(regime_types),
        "market_regime_types": regime_types,
        "market_regime_source": "as_of_date",
        "market_regime_source_text_grounded": False,
        "market_regime_details": details,
        "market_regime_policy": (
            "Market regime is inferred from the PIT report as-of date using the "
            "governed macro regime calendar; it is not treated as source-text "
            "grounded report prose."
        ),
    }


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


def _clean_bucket_text(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower() in {"", "nan", "none", "null"}:
        return ""
    return text


def _looks_like_stock_code(value: Any) -> bool:
    text = str(value or "").strip().upper()
    return bool(re.fullmatch(r"\d{6}(\.(SH|SZ|BJ))?", text))


def _report_sector_bucket(row: Mapping[str, Any]) -> str:
    for field in ("sector", "industry", "ind_name"):
        value = _clean_bucket_text(row.get(field))
        if value and not _looks_like_stock_code(value):
            return value
    query_key = _clean_bucket_text(row.get("query_key"))
    if query_key and not _looks_like_stock_code(query_key):
        return query_key
    return "unknown_sector"


def _coverage_sector_bucket(row: Mapping[str, Any]) -> str:
    return _coverage_sector_family(_report_sector_bucket(row))


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


def _markdown_gap_retryable(gap: str) -> bool:
    return any(marker in gap for marker in MARKDOWN_RETRYABLE_GAP_MARKERS)


def _markdown_gap_false_positive_risk(gap: str) -> bool:
    return gap in MARKDOWN_FALSE_POSITIVE_RISK_GAPS


def _coverage_metadata_datetime(row: Mapping[str, Any]) -> datetime | None:
    for field in ("publish_datetime", "accessible_datetime", "publish_date"):
        parsed = _parse_pit_datetime(row.get(field))
        if parsed is not None:
            return parsed
    return None


def _coverage_corpus_as_of(metadata_rows: Sequence[Mapping[str, Any]]) -> datetime | None:
    dates = [
        parsed
        for row in metadata_rows
        if (parsed := _coverage_metadata_datetime(row)) is not None
    ]
    return max(dates) if dates else None


def _coverage_time_bucket(
    row: Mapping[str, Any],
    *,
    corpus_as_of: datetime | None,
) -> str:
    report_date = _coverage_metadata_datetime(row)
    if report_date is None:
        return "date_missing"
    if corpus_as_of is None:
        return "date_unbucketed"
    age_days = (corpus_as_of.date() - report_date.date()).days
    if age_days < 0:
        return "future_report_date"
    if age_days <= 365:
        return "recent_1y"
    if age_days <= 365 * 3:
        return "recent_3y"
    return "long_cycle_history"


def _coverage_stock_outcome_age_bucket(
    row: Mapping[str, Any],
    *,
    corpus_as_of: datetime | None,
) -> str:
    if not _is_potential_stock_report(row):
        return "non_stock_report"
    if not _is_explicit_stock_ts_code(row.get("ts_code")):
        return "stock_ts_code_missing"
    report_date = _coverage_metadata_datetime(row)
    if report_date is None:
        return "stock_report_date_missing"
    if corpus_as_of is None:
        return "stock_outcome_age_unbucketed"
    age_days = (corpus_as_of.date() - report_date.date()).days
    if age_days < 0:
        return "stock_future_report_date"
    if age_days >= 180:
        return "stock_outcome_120d_calendar_ready"
    if age_days >= 90:
        return "stock_outcome_60d_calendar_ready"
    if age_days >= 30:
        return "stock_outcome_20d_calendar_ready"
    if age_days >= 10:
        return "stock_outcome_5d_calendar_ready"
    return "stock_outcome_pending"


def _coverage_report_key(row: Mapping[str, Any]) -> str:
    return str(row.get("source_id") or row.get("report_id") or "").strip()


def _coverage_forecast_rows_by_report(
    forecast_rows: Sequence[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    rows_by_report: dict[str, list[Mapping[str, Any]]] = {}
    for row in forecast_rows:
        key = _coverage_report_key(row)
        if key:
            rows_by_report.setdefault(key, []).append(row)
    return rows_by_report


def _coverage_institution_counts(
    metadata_rows: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in metadata_rows:
        key = str(row.get("institution_id") or row.get("institution") or "").strip()
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def _coverage_institution_bucket(
    row: Mapping[str, Any],
    *,
    institution_counts: Mapping[str, int],
    total_reports: int,
) -> str:
    key = str(row.get("institution_id") or row.get("institution") or "").strip()
    if not key:
        return "missing_institution"
    head_threshold = max(10, (max(total_reports, 1) + 19) // 20)
    if institution_counts.get(key, 0) >= head_threshold:
        return "head_institution"
    return "long_tail_institution"


def _coverage_horizon_buckets_for_report(
    forecast_rows: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
) -> set[str]:
    explicit_buckets = {
        _horizon_bucket(_ensure_mapping(row.get("horizon")))
        for row in forecast_rows
    }
    explicit_buckets.discard("")
    buckets = {bucket for bucket in explicit_buckets if bucket != "unknown"}
    if not buckets and forecast_rows:
        # If the report lacks an explicit claim horizon but is proxy-evaluable,
        # count the PIT windows that the outcome labelers will retain.
        if any(_is_stock_forecast_claim(forecast, metadata) for forecast in forecast_rows):
            buckets.update(_horizon_bucket({"preferred_days": days}) for days in STOCK_PRICE_PROXY_WINDOWS_DAYS)
        if _is_industry_research_report(metadata.get("report_type")):
            buckets.update(_horizon_bucket({"preferred_days": days}) for days in INDUSTRY_ETF_PROXY_WINDOWS_DAYS)
    if "unknown" in explicit_buckets:
        buckets.add("unknown")
    return buckets or {"no_extracted_forecast_horizon"}


def _coverage_evaluability_buckets_for_report(
    row: Mapping[str, Any],
    forecast_rows: Sequence[Mapping[str, Any]],
    *,
    markdown_gap: str,
) -> set[str]:
    markdown = _ensure_mapping(row.get("markdown"))
    extraction = _ensure_mapping(row.get("extraction"))
    if not _is_markdown_ready(markdown):
        return {"markdown_not_ready"}
    if markdown_gap:
        return {"quality_gate_blocked"}
    if str(extraction.get("llm_status") or "") != "processed":
        return {"llm_extraction_pending"}
    if not forecast_rows:
        return {"no_forecast_claim_extracted"}
    buckets: set[str] = set()
    if any(_forecast_mapping_gaps(forecast) for forecast in forecast_rows):
        buckets.add("mapping_gap_candidate")
    if any(_is_stock_forecast_claim(forecast, row) for forecast in forecast_rows):
        buckets.add("stock_proxy_candidate")
    if _is_industry_research_report(row.get("report_type")):
        buckets.add("industry_proxy_candidate")
    return buckets or {"standard_evaluable_candidate"}


def _coverage_missing_required_buckets(
    counts: Mapping[str, int],
    required_buckets: Sequence[str],
    *,
    dimension: str,
) -> list[str]:
    return [
        f"{dimension}:{bucket}"
        for bucket in required_buckets
        if int(counts.get(bucket) or 0) <= 0
    ]


def _sector_bucket_coverage_gaps(
    sector_bucket_counts: Mapping[str, int],
) -> list[str]:
    return [
        f"sector_bucket:{bucket}"
        for bucket, count in sorted(sector_bucket_counts.items())
        if bucket and int(count or 0) < MARKDOWN_COVERAGE_MIN_REPORTS_PER_SECTOR_BUCKET
    ]


_SECTOR_FAMILY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("technology_electronics", ("半导体", "电子", "元件", "光学", "通信", "通讯", "计算机", "软件", "互联网", "IT服务", "数字媒体", "游戏")),
    ("healthcare", ("医药", "医疗", "生物", "中药", "化学制药", "医疗器械", "医疗服务")),
    ("financials", ("银行", "证券", "保险", "金融", "券商", "信托")),
    ("real_estate_construction", ("房地产", "建筑", "工程", "装修", "建材", "水泥", "园林", "基础建设", "房屋建设")),
    ("energy_materials", ("有色", "金属", "钢铁", "煤炭", "石油", "油气", "化工", "化学", "材料", "塑料", "橡胶", "玻璃", "电池", "光伏", "风电", "新能源")),
    ("industrial_equipment", ("机械", "设备", "仪器", "电机", "电网", "自动化", "轨交", "船舶", "航天", "航空", "军工", "兵装", "电源")),
    ("consumer", ("食品", "饮料", "白酒", "家电", "家居", "服装", "纺织", "美容", "化妆", "零售", "电商", "旅游", "酒店", "餐饮", "教育", "文娱", "传媒", "体育", "珠宝", "饰品", "个护")),
    ("auto_transport", ("汽车", "乘用车", "商用车", "摩托", "交运", "物流", "港口", "航运", "机场", "铁路", "公路")),
    ("utilities_environment", ("电力", "燃气", "公用事业", "环保", "环境", "水务")),
    ("agriculture", ("农业", "农", "养殖", "种植", "饲料", "动物保健")),
)


def _coverage_sector_family(raw_sector: str) -> str:
    normalized = raw_sector.strip()
    if not normalized or normalized == "unknown_sector":
        return "other_sector"
    if any(keyword in normalized for keyword in ("宏观", "策略", "固收", "金融工程", "行业研报")):
        return "other_sector"
    for family, keywords in _SECTOR_FAMILY_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return family
    return "other_sector"


def build_markdown_coverage_summary(
    *,
    run_id: str,
    metadata_rows: Sequence[Mapping[str, Any]],
    forecast_rows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    report_type_counts: dict[str, int] = {}
    time_bucket_counts: dict[str, int] = {}
    institution_bucket_counts: dict[str, int] = {}
    sector_bucket_counts: dict[str, int] = {}
    report_horizon_bucket_counts: dict[str, int] = {}
    forecast_horizon_bucket_counts: dict[str, int] = {}
    evaluability_bucket_counts: dict[str, int] = {}
    stock_outcome_age_bucket_counts: dict[str, int] = {}
    conversion_backend_counts: dict[str, int] = {}
    quality_gap_counts: dict[str, int] = {}
    quality_review_gap_counts: dict[str, int] = {}
    false_positive_risk_gap_counts: dict[str, int] = {}
    industry_report_count = 0
    stock_report_count = 0
    pdf_ready_count = 0
    markdown_ready_count = 0
    markdown_quality_pass_count = 0
    llm_extraction_processed_count = 0
    llm_extraction_without_quality_pass_count = 0
    retry_queue_count = 0
    quality_review_queue_count = 0
    false_positive_review_queue_count = 0
    corpus_as_of = _coverage_corpus_as_of(metadata_rows)
    forecast_rows_by_report = _coverage_forecast_rows_by_report(forecast_rows)
    institution_counts = _coverage_institution_counts(metadata_rows)
    for row in metadata_rows:
        _increment_count(report_type_counts, row.get("report_type"))
        _increment_count(
            time_bucket_counts,
            _coverage_time_bucket(row, corpus_as_of=corpus_as_of),
        )
        _increment_count(
            institution_bucket_counts,
            _coverage_institution_bucket(
                row,
                institution_counts=institution_counts,
                total_reports=len(metadata_rows),
            ),
        )
        _increment_count(
            sector_bucket_counts,
            _coverage_sector_bucket(row),
            default="unknown_sector",
        )
        if _is_industry_research_report(row.get("report_type")):
            industry_report_count += 1
        if _is_explicit_stock_research_report(row):
            stock_report_count += 1
            _increment_count(
                stock_outcome_age_bucket_counts,
                _coverage_stock_outcome_age_bucket(
                    row,
                    corpus_as_of=corpus_as_of,
                ),
            )
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
            if _markdown_gap_retryable(gap):
                retry_queue_count += 1
            elif _is_markdown_ready(markdown):
                quality_review_queue_count += 1
                _increment_count(quality_review_gap_counts, gap)
                if _markdown_gap_false_positive_risk(gap):
                    false_positive_review_queue_count += 1
                    _increment_count(false_positive_risk_gap_counts, gap)
        else:
            markdown_quality_pass_count += 1
        extraction = _ensure_mapping(row.get("extraction"))
        if str(extraction.get("llm_status") or "") == "processed":
            llm_extraction_processed_count += 1
            if gap:
                llm_extraction_without_quality_pass_count += 1
        report_forecasts = forecast_rows_by_report.get(_coverage_report_key(row), [])
        for bucket in sorted(
            _coverage_horizon_buckets_for_report(report_forecasts, row)
        ):
            _increment_count(report_horizon_bucket_counts, bucket)
        for forecast in report_forecasts:
            _increment_count(
                forecast_horizon_bucket_counts,
                _horizon_bucket(_ensure_mapping(forecast.get("horizon"))),
            )
        for bucket in sorted(
            _coverage_evaluability_buckets_for_report(
                row,
                report_forecasts,
                markdown_gap=gap,
            )
        ):
            _increment_count(evaluability_bucket_counts, bucket)
    coverage_targets = {
        "selected_report_count_min": MARKDOWN_COVERAGE_MIN_SELECTED_REPORTS,
        "markdown_ready_count_min": MARKDOWN_COVERAGE_MIN_MARKDOWN_READY,
        "markdown_quality_pass_count_min": MARKDOWN_COVERAGE_MIN_QUALITY_PASS,
        "llm_extraction_processed_count_min": (
            MARKDOWN_COVERAGE_MIN_LLM_EXTRACTION_PROCESSED
        ),
        "industry_report_count_min": MARKDOWN_COVERAGE_MIN_INDUSTRY_REPORTS,
        "stock_report_count_min": MARKDOWN_COVERAGE_MIN_STOCK_REPORTS,
        "stock_outcome_120d_ready_report_count_min": (
            MARKDOWN_COVERAGE_MIN_STOCK_OUTCOME_120D_READY_REPORTS
        ),
        "sector_bucket_min_report_count": (
            MARKDOWN_COVERAGE_MIN_REPORTS_PER_SECTOR_BUCKET
        ),
    }
    sector_bucket_coverage_gaps = _sector_bucket_coverage_gaps(sector_bucket_counts)
    coverage_strata_targets = {
        "time_bucket_required": list(MARKDOWN_COVERAGE_REQUIRED_TIME_BUCKETS),
        "institution_bucket_required": list(
            MARKDOWN_COVERAGE_REQUIRED_INSTITUTION_BUCKETS
        ),
        "horizon_bucket_required": list(
            MARKDOWN_COVERAGE_REQUIRED_HORIZON_BUCKETS
        ),
        "evaluability_bucket_required": list(
            MARKDOWN_COVERAGE_REQUIRED_EVALUABILITY_BUCKETS
        ),
        "stock_outcome_age_bucket_required": list(
            MARKDOWN_COVERAGE_REQUIRED_STOCK_OUTCOME_AGE_BUCKETS
        ),
    }
    coverage_strata_missing = [
        *_coverage_missing_required_buckets(
            time_bucket_counts,
            MARKDOWN_COVERAGE_REQUIRED_TIME_BUCKETS,
            dimension="time_bucket",
        ),
        *_coverage_missing_required_buckets(
            institution_bucket_counts,
            MARKDOWN_COVERAGE_REQUIRED_INSTITUTION_BUCKETS,
            dimension="institution_bucket",
        ),
        *_coverage_missing_required_buckets(
            report_horizon_bucket_counts,
            MARKDOWN_COVERAGE_REQUIRED_HORIZON_BUCKETS,
            dimension="horizon_bucket",
        ),
        *_coverage_missing_required_buckets(
            evaluability_bucket_counts,
            MARKDOWN_COVERAGE_REQUIRED_EVALUABILITY_BUCKETS,
            dimension="evaluability_bucket",
        ),
        *_coverage_missing_required_buckets(
            stock_outcome_age_bucket_counts,
            MARKDOWN_COVERAGE_REQUIRED_STOCK_OUTCOME_AGE_BUCKETS,
            dimension="stock_outcome_age_bucket",
        ),
    ]
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
    if industry_report_count < MARKDOWN_COVERAGE_MIN_INDUSTRY_REPORTS:
        coverage_gate_blockers.append("industry_report_count_below_p9_target")
    if stock_report_count < MARKDOWN_COVERAGE_MIN_STOCK_REPORTS:
        coverage_gate_blockers.append("stock_report_count_below_p9_target")
    stock_outcome_120d_ready_count = int(
        stock_outcome_age_bucket_counts.get("stock_outcome_120d_calendar_ready") or 0
    )
    if (
        stock_outcome_120d_ready_count
        < MARKDOWN_COVERAGE_MIN_STOCK_OUTCOME_120D_READY_REPORTS
    ):
        coverage_gate_blockers.append(
            "stock_outcome_120d_ready_count_below_p9_target"
        )
    if sector_bucket_coverage_gaps:
        coverage_gate_blockers.append("sector_bucket_coverage_below_p9_target")
    if any(item.startswith("time_bucket:") for item in coverage_strata_missing):
        coverage_gate_blockers.append("time_bucket_coverage_below_p9_target")
    if any(item.startswith("institution_bucket:") for item in coverage_strata_missing):
        coverage_gate_blockers.append("institution_bucket_coverage_below_p9_target")
    if any(item.startswith("horizon_bucket:") for item in coverage_strata_missing):
        coverage_gate_blockers.append("horizon_bucket_coverage_below_p9_target")
    if any(item.startswith("evaluability_bucket:") for item in coverage_strata_missing):
        coverage_gate_blockers.append("evaluability_bucket_coverage_below_p9_target")
    if any(
        item.startswith("stock_outcome_age_bucket:")
        for item in coverage_strata_missing
    ):
        coverage_gate_blockers.append(
            "stock_outcome_age_bucket_coverage_below_p9_target"
        )
    if llm_extraction_without_quality_pass_count:
        coverage_gate_blockers.append("llm_extraction_without_quality_pass")
    coverage_shortfalls = {
        "selected_report_count": _threshold_shortfall(
            current=len(metadata_rows),
            target=MARKDOWN_COVERAGE_MIN_SELECTED_REPORTS,
            blocker="selected_report_count_below_p9_target",
            next_action="add_stratified_real_reports_to_private_source_pool",
        ),
        "markdown_ready_count": _threshold_shortfall(
            current=markdown_ready_count,
            target=MARKDOWN_COVERAGE_MIN_MARKDOWN_READY,
            blocker="markdown_ready_count_below_p9_target",
            next_action="download_pdfs_and_convert_quality_gated_markdown",
        ),
        "markdown_quality_pass_count": _threshold_shortfall(
            current=markdown_quality_pass_count,
            target=MARKDOWN_COVERAGE_MIN_QUALITY_PASS,
            blocker="markdown_quality_pass_count_below_p9_target",
            next_action="resolve_markdown_quality_gaps_before_llm_extraction",
        ),
        "llm_extraction_processed_count": _threshold_shortfall(
            current=llm_extraction_processed_count,
            target=MARKDOWN_COVERAGE_MIN_LLM_EXTRACTION_PROCESSED,
            blocker="llm_extraction_processed_count_below_p9_target",
            next_action="run_llm_extraction_on_quality_passed_markdown",
        ),
        "industry_report_count": _threshold_shortfall(
            current=industry_report_count,
            target=MARKDOWN_COVERAGE_MIN_INDUSTRY_REPORTS,
            blocker="industry_report_count_below_p9_target",
            next_action="add_more_industry_research_reports_to_stratified_pool",
        ),
        "stock_report_count": _threshold_shortfall(
            current=stock_report_count,
            target=MARKDOWN_COVERAGE_MIN_STOCK_REPORTS,
            blocker="stock_report_count_below_p9_target",
            next_action="add_more_stock_research_reports_with_ts_code",
        ),
        "stock_outcome_120d_ready_report_count": _threshold_shortfall(
            current=stock_outcome_120d_ready_count,
            target=MARKDOWN_COVERAGE_MIN_STOCK_OUTCOME_120D_READY_REPORTS,
            blocker="stock_outcome_120d_ready_count_below_p9_target",
            next_action="prefer_historical_stock_reports_with_120d_outcome_windows",
        ),
        "sector_bucket_below_min_count": {
            "current": len(sector_bucket_coverage_gaps),
            "target": 0,
            "remaining": len(sector_bucket_coverage_gaps),
            "blocker": "sector_bucket_coverage_below_p9_target",
            "next_action": "fill_aggregate_sector_bucket_coverage_gaps",
        },
        "coverage_strata_missing_count": {
            "current": len(coverage_strata_missing),
            "target": 0,
            "remaining": len(coverage_strata_missing),
            "blocker": "stratified_coverage_below_p9_target",
            "next_action": "fill_missing_time_institution_horizon_evaluability_strata",
        },
    }
    summary = {
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
        "industry_report_count": industry_report_count,
        "stock_report_count": stock_report_count,
        "stock_outcome_120d_ready_report_count": stock_outcome_120d_ready_count,
        "coverage_targets": coverage_targets,
        "coverage_shortfalls": coverage_shortfalls,
        "sector_bucket_coverage_gaps": sector_bucket_coverage_gaps,
        "sector_bucket_below_min_count": len(sector_bucket_coverage_gaps),
        "coverage_strata_targets": coverage_strata_targets,
        "coverage_strata_missing": coverage_strata_missing,
        "coverage_gate_status": (
            "passed" if not coverage_gate_blockers else "blocked"
        ),
        "coverage_gate_blockers": coverage_gate_blockers,
        "markdown_quality_gap_counts": dict(sorted(quality_gap_counts.items())),
        "markdown_quality_review_queue_count": quality_review_queue_count,
        "markdown_quality_review_gap_counts": dict(
            sorted(quality_review_gap_counts.items())
        ),
        "markdown_false_positive_review_queue_count": (
            false_positive_review_queue_count
        ),
        "markdown_false_positive_risk_gap_counts": dict(
            sorted(false_positive_risk_gap_counts.items())
        ),
        "markdown_quality_spot_check_required": quality_review_queue_count > 0,
        "report_type_counts": dict(sorted(report_type_counts.items())),
        "time_bucket_counts": dict(sorted(time_bucket_counts.items())),
        "institution_bucket_counts": dict(sorted(institution_bucket_counts.items())),
        "sector_bucket_counts": dict(sorted(sector_bucket_counts.items())),
        "report_horizon_bucket_counts": dict(
            sorted(report_horizon_bucket_counts.items())
        ),
        "forecast_horizon_bucket_counts": dict(
            sorted(forecast_horizon_bucket_counts.items())
        ),
        "evaluability_bucket_counts": dict(sorted(evaluability_bucket_counts.items())),
        "stock_outcome_age_bucket_counts": dict(
            sorted(stock_outcome_age_bucket_counts.items())
        ),
        "conversion_backend_counts": dict(sorted(conversion_backend_counts.items())),
        "retry_queue_count": retry_queue_count,
        "stratified_sampling_policy": {
            "required_dimensions": [
                "report_type",
                "time_bucket",
                "institution_bucket",
                "sector_bucket",
                "stock_ts_code",
                "stock_outcome_age_bucket",
                "horizon_bucket",
                "evaluability_bucket",
            ],
            "industry_report_count_min": MARKDOWN_COVERAGE_MIN_INDUSTRY_REPORTS,
            "stock_report_with_ts_code_count_min": (
                MARKDOWN_COVERAGE_MIN_STOCK_REPORTS
            ),
            "sector_bucket_policy": (
                "sector_bucket_counts are aggregate-only; high-frequency "
                "sector minimums are evaluated from the private source universe "
                "and recorded as coverage gaps before evolution promotion"
            ),
            "privacy_boundary": "aggregate_counts_only",
        },
        "markdown_quality_review_policy": (
            "ready Markdown blocked by quality gates enters aggregate manual "
            "review counts before extraction is trusted; repeated-line, sparse "
            "structure, short, and empty-table gaps are tracked as false-positive "
            "risk classes for corpus spot checks"
        ),
        "private_artifact_redaction_policy": (
            "public coverage summary stores aggregate counts only; no "
            "source-specific content, retrieval locator, local file reference, "
            "or report prose is allowed"
        ),
    }
    summary["private_text_included"] = _public_payload_private_text_included(summary)
    return summary


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
    default_rows = build_default_industry_etf_proxy_map_rows()
    default_by_sector = {
        str(row.get("sector_name") or "").strip(): row
        for row in default_rows
        if str(row.get("sector_name") or "").strip()
    }
    rows, _errors = load_jsonl_with_errors(map_path, label="industry_etf_proxy_map")
    mapping_rows = [row for row in rows if isinstance(row, Mapping)]
    if not mapping_rows:
        return default_rows
    refreshed_rows: list[Mapping[str, Any]] = []
    for row in mapping_rows:
        sector = str(row.get("sector_name") or "").strip()
        default_row = default_by_sector.get(sector)
        if (
            default_row is not None
            and str(row.get("taxonomy") or "") == "operator_seeded_tushare_industry"
            and str(row.get("mapping_confidence") or "")
            == "operator_seeded_exact_sector"
            and str(row.get("status") or "primary") == "primary"
            and not bool(row.get("review_required"))
        ):
            refreshed_rows.append(default_row)
        else:
            refreshed_rows.append(row)
    configured_sectors = {
        str(row.get("sector_name") or "").strip()
        for row in refreshed_rows
        if str(row.get("sector_name") or "").strip()
    }
    fallback_rows = [
        row
        for row in default_rows
        if str(row.get("sector_name") or "").strip() not in configured_sectors
    ]
    return [*refreshed_rows, *fallback_rows]


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


def _industry_pit_availability_by_mapping_id(
    pit_availability: Mapping[str, Any] | None,
) -> dict[str, Mapping[str, Any]]:
    if not pit_availability:
        return {}
    return {
        str(row.get("mapping_id") or ""): row
        for row in _ensure_list(_ensure_mapping(pit_availability).get("mapping_records"))
        if isinstance(row, Mapping) and str(row.get("mapping_id") or "").strip()
    }


def _industry_pit_availability_gap(
    mapping: Mapping[str, Any],
    availability_by_mapping_id: Mapping[str, Mapping[str, Any]],
) -> str:
    if not availability_by_mapping_id:
        return ""
    mapping_id = str(mapping.get("mapping_id") or "")
    record = availability_by_mapping_id.get(mapping_id)
    if not record:
        return "pit_availability_missing"
    if record.get("pit_available") is True:
        return ""
    reasons = [str(item) for item in _ensure_list(record.get("pit_gap_reasons"))]
    for reason in ("calendar_missing", "proxy_series_missing", "benchmark_series_missing"):
        if reason in reasons:
            return reason
    if "insufficient_window_history" in reasons:
        return "pit_availability_insufficient_window_history"
    return "pit_availability_unavailable"


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


def _stock_series_coverage_summary(
    *,
    target_series_count: int,
    target_series_missing_count: int,
    earliest_price_dates: Sequence[str],
    latest_price_dates: Sequence[str],
    latest_calendar_date: str,
    entry_before_series_start_count: int,
    entry_after_series_end_count: int,
    entry_within_series_range_count: int,
) -> dict[str, Any]:
    lifecycle_counts: dict[str, int] = {}
    for latest_price_date in latest_price_dates:
        if not latest_calendar_date:
            status = "calendar_missing"
        elif latest_price_date == latest_calendar_date:
            status = "latest_aligned"
        elif latest_price_date < latest_calendar_date:
            status = "stale_before_latest_calendar"
        else:
            status = "future_dated"
        _increment_count(lifecycle_counts, status)
    return {
        "target_series_count": int(target_series_count),
        "target_series_missing_count": int(target_series_missing_count),
        "earliest_price_date_min": min(earliest_price_dates)
        if earliest_price_dates
        else "",
        "earliest_price_date_max": max(earliest_price_dates)
        if earliest_price_dates
        else "",
        "latest_price_date_min": min(latest_price_dates)
        if latest_price_dates
        else "",
        "latest_price_date_max": max(latest_price_dates)
        if latest_price_dates
        else "",
        "latest_calendar_date": latest_calendar_date,
        "latest_aligned_series_count": int(lifecycle_counts.get("latest_aligned") or 0),
        "stale_before_latest_calendar_count": int(
            lifecycle_counts.get("stale_before_latest_calendar") or 0
        ),
        "future_dated_series_count": int(lifecycle_counts.get("future_dated") or 0),
        "series_lifecycle_status_counts": dict(sorted(lifecycle_counts.items())),
        "entry_before_series_start_count": int(entry_before_series_start_count),
        "entry_after_series_end_count": int(entry_after_series_end_count),
        "entry_within_series_range_count": int(entry_within_series_range_count),
    }


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
    qlib_source_label = _public_qlib_source_label(qlib_etf_dir)
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
                "calendar_source": qlib_source_label,
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
            entry_lag_trading_days=INDUSTRY_ETF_ENTRY_LAG_TRADING_DAYS,
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
        "qlib_etf_dir_configured": qlib_source_label,
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


def _industry_pit_labelability_summary_from_readiness(
    industry_etf_proxy_readiness: Mapping[str, Any],
) -> dict[str, Any]:
    readiness = _ensure_mapping(industry_etf_proxy_readiness)
    data_gap_counts = _count_mapping_values(
        _ensure_mapping(readiness.get("data_gap_counts"))
    )
    return {
        "eligible_claim_count": int(readiness.get("eligible_claim_count") or 0),
        "labelable_claim_count": int(
            readiness.get("labelable_forecast_claim_count") or 0
        ),
        "labelable_window_count": int(
            readiness.get("labelable_window_count") or 0
        ),
        "pending_future_window_count": int(
            readiness.get("pending_future_window_count") or 0
        ),
        "sector_etf_mapping_missing_count": data_gap_counts.get(
            "sector_etf_mapping_missing",
            0,
        ),
        "proxy_series_missing_count": data_gap_counts.get(
            "proxy_series_missing",
            0,
        ),
        "benchmark_series_missing_count": data_gap_counts.get(
            "benchmark_series_missing",
            0,
        ),
        "data_gap_counts": data_gap_counts,
    }


def _with_industry_pit_labelability_summary(
    pit_availability: Mapping[str, Any],
    industry_etf_proxy_readiness: Mapping[str, Any],
) -> dict[str, Any]:
    updated = dict(pit_availability)
    updated["labelability_summary"] = (
        _industry_pit_labelability_summary_from_readiness(
            industry_etf_proxy_readiness
        )
    )
    return updated


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
    availability_by_mapping_id = _industry_pit_availability_by_mapping_id(
        pit_availability
    )
    qlib_dir = _resolve_qlib_etf_dir(root_path, qlib_etf_dir)
    qlib_source_label = _public_qlib_source_label(qlib_etf_dir)
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
    pending_future_claim_ids: list[str] = []
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
        pit_gap = _industry_pit_availability_gap(proxy, availability_by_mapping_id)
        if pit_gap:
            add_gap(pit_gap)
            continue
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
            entry_lag_trading_days=INDUSTRY_ETF_ENTRY_LAG_TRADING_DAYS,
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
        claim_pending_future_window_count = 0
        claim_window_gap_count = 0
        for horizon_days in windows_days:
            exit_index = entry_index + int(horizon_days)
            if exit_index >= len(calendar):
                pending_future_window_count += 1
                claim_pending_future_window_count += 1
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
                claim_window_gap_count += 1
                continue
            labelable_window_count += 1
            claim_labelable_window_count += 1
        if claim_labelable_window_count:
            labelable_claim_ids.append(forecast_claim_id)
        elif claim_pending_future_window_count and not claim_window_gap_count:
            pending_future_claim_ids.append(forecast_claim_id)
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
        "qlib_etf_dir_configured": qlib_source_label,
        "latest_calendar_date": calendar[-1] if calendar else "",
        "mapping_count": len(mapping_rows),
        "eligible_claim_count": len(eligible_claim_ids),
        "eligible_forecast_claim_ids": eligible_claim_ids,
        "labelable_forecast_claim_count": len(labelable_claim_ids),
        "labelable_forecast_claim_ids": labelable_claim_ids,
        "labelable_window_count": labelable_window_count,
        "pending_future_window_count": pending_future_window_count,
        "pending_future_forecast_claim_count": len(pending_future_claim_ids),
        "pending_future_forecast_claim_ids": pending_future_claim_ids,
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
    stock_source_label = _public_qlib_source_label(qlib_stock_dir)
    benchmark_source_label = _public_qlib_source_label(qlib_etf_dir)
    stock_calendar = _read_trading_calendar(stock_dir)
    benchmark_calendar = _read_trading_calendar(benchmark_dir)
    benchmark_start, benchmark_values = _read_qlib_series(
        benchmark_dir,
        benchmark_symbol,
    )
    metadata_by_source = _source_report_metadata(metadata_rows)
    eligible_claim_ids: list[str] = []
    labelable_claim_ids: list[str] = []
    pending_future_claim_ids: list[str] = []
    data_gap_counts: dict[str, int] = {}
    labelable_window_count = 0
    pending_future_window_count = 0
    target_symbols_with_series: set[str] = set()
    target_symbols_missing_series: set[str] = set()
    target_series_spans: dict[str, tuple[str, str]] = {}
    earliest_price_dates: list[str] = []
    latest_price_dates: list[str] = []
    entry_before_series_start_count = 0
    entry_after_series_end_count = 0
    entry_within_series_range_count = 0

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
            target_symbols_missing_series.add(ts_code)
            add_gap("stock_series_missing")
            continue
        available_dates = _series_available_dates(
            calendar=stock_calendar,
            start_index=stock_start,
            values=stock_values,
        )
        if available_dates:
            target_symbols_with_series.add(ts_code)
            if ts_code not in target_series_spans:
                target_series_spans[ts_code] = (
                    available_dates[0],
                    available_dates[-1],
                )
                earliest_price_dates.append(available_dates[0])
                latest_price_dates.append(available_dates[-1])
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
            entry_lag_trading_days=STOCK_PRICE_PROXY_ENTRY_LAG_TRADING_DAYS,
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
            if available_dates and entry_date < available_dates[0]:
                entry_before_series_start_count += 1
                add_gap("entry_price_before_series_start")
            elif available_dates and entry_date > available_dates[-1]:
                entry_after_series_end_count += 1
                add_gap("entry_price_after_series_end")
            else:
                add_gap("entry_price_missing")
            continue
        entry_within_series_range_count += 1
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
        latest_stock_price_date = available_dates[-1] if available_dates else ""
        claim_labelable_window_count = 0
        claim_pending_future_window_count = 0
        claim_window_gap_count = 0
        for horizon_days in windows_days:
            exit_index = entry_index + int(horizon_days)
            if exit_index >= len(stock_calendar):
                pending_future_window_count += 1
                claim_pending_future_window_count += 1
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
                claim_window_gap_count += 1
                continue
            exit_volume_ok = _has_positive_volume_at(
                start_index=volume_start,
                values=volume_values,
                calendar_index=exit_index,
            )
            if exit_volume_ok is False:
                add_gap("stock_long_suspension_window")
                claim_window_gap_count += 1
                continue
            if exit_volume_ok is None:
                add_gap("exit_liquidity_unverified")
                claim_window_gap_count += 1
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
                claim_window_gap_count += 1
                continue
            if exit_locked is None:
                add_gap("exit_liquidity_unverified")
                claim_window_gap_count += 1
                continue
            if _series_value_at_date(
                calendar=benchmark_calendar,
                start_index=benchmark_start,
                values=benchmark_values,
                date_value=exit_date,
            ) is None:
                add_gap("benchmark_series_missing")
                claim_window_gap_count += 1
                continue
            labelable_window_count += 1
            claim_labelable_window_count += 1
        if claim_labelable_window_count:
            labelable_claim_ids.append(forecast_claim_id)
        elif claim_pending_future_window_count and not claim_window_gap_count:
            pending_future_claim_ids.append(forecast_claim_id)
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
        "ordinary_stock_code_policy": STOCK_PRICE_PROXY_CODE_POLICY,
        "qlib_stock_dir_configured": stock_source_label,
        "qlib_benchmark_dir_configured": benchmark_source_label,
        "latest_calendar_date": stock_calendar[-1] if stock_calendar else "",
        "eligible_claim_count": len(eligible_claim_ids),
        "eligible_forecast_claim_ids": eligible_claim_ids,
        "labelable_forecast_claim_count": len(labelable_claim_ids),
        "labelable_forecast_claim_ids": labelable_claim_ids,
        "labelable_window_count": labelable_window_count,
        "pending_future_window_count": pending_future_window_count,
        "pending_future_forecast_claim_count": len(pending_future_claim_ids),
        "pending_future_forecast_claim_ids": pending_future_claim_ids,
        "data_gap_counts": dict(sorted(data_gap_counts.items())),
        "stock_series_coverage_summary": _stock_series_coverage_summary(
            target_series_count=len(target_symbols_with_series),
            target_series_missing_count=len(target_symbols_missing_series),
            earliest_price_dates=earliest_price_dates,
            latest_price_dates=latest_price_dates,
            latest_calendar_date=stock_calendar[-1] if stock_calendar else "",
            entry_before_series_start_count=entry_before_series_start_count,
            entry_after_series_end_count=entry_after_series_end_count,
            entry_within_series_range_count=entry_within_series_range_count,
        ),
        "pit_realism_policy": {
            "entry_suspension_blocks_label": True,
            "entry_limit_locked_blocks_label": True,
            "exit_liquidity_unverified_blocks_label": True,
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
    availability_by_mapping_id = _industry_pit_availability_by_mapping_id(
        pit_availability
    )
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
        if _industry_pit_availability_gap(proxy, availability_by_mapping_id):
            continue
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
        market_regime_fields = _as_of_date_market_regime_fields(
            claim.get("signal_datetime")
        )
        entry_index = _entry_calendar_index(
            calendar,
            str(claim.get("signal_datetime") or ""),
            entry_lag_trading_days=INDUSTRY_ETF_ENTRY_LAG_TRADING_DAYS,
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
                            "label_type": "industry_etf_proxy",
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
                    **market_regime_fields,
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
            entry_lag_trading_days=STOCK_PRICE_PROXY_ENTRY_LAG_TRADING_DAYS,
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
        market_regime_fields = _as_of_date_market_regime_fields(
            claim.get("signal_datetime")
        )
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
                "entry_tradable": True,
                "exit_tradable": True,
                "entry_limit_locked": False,
                "exit_limit_locked": False,
                "entry_liquidity_check": STOCK_PRICE_PROXY_TRADABILITY_CHECK,
                "exit_liquidity_check": STOCK_PRICE_PROXY_TRADABILITY_CHECK,
                **market_regime_fields,
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
        if not gap_id or str(gap.get("status") or "") == "retired":
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
        if not gap_id or str(gap.get("status") or "") == "retired":
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
ANALYSIS_RECIPE_DEFAULT_REQUIRED_DATA = (
    "stock_price",
    "benchmark_return",
)
ANALYSIS_RECIPE_RISK_CONTROLS = (
    "no_production_order",
    "no_position_sizing",
    "after_cost_alpha_required",
    "consecutive_after_cost_decay_blocks_validation",
    "turnover_cost_decay_blocks_validation",
    "drawdown_threshold_pre_registered",
)
ANALYSIS_RECIPE_REASONING_STEP_TOOL = "analysis.reasoning_step"
ANALYSIS_RECIPE_REASONING_STEP_KEYWORDS = (
    "analyze",
    "assess",
    "evaluate",
    "analysis",
    "compare",
    "comparison",
    "identify",
    "interpretation",
    "breakdown",
    "impact",
    "tracking",
    "calculation",
    "modeling",
    "projection",
    "identification",
    "positioning",
    "derivation",
    "estimation",
    "adjustment",
    "timeline",
    "comparable",
    "assign_rating",
    "set_time_horizon",
    "define_",
    "project_future",
    "monitor_",
    "track_",
    "map_to",
    "correlate",
    "分析",
    "评估",
    "识别",
    "比较",
    "判断",
    "预测",
    "监控",
    "跟踪",
    "计算",
    "推算",
    "评级",
    "对比",
    "定性",
    "引用",
    "增长",
    "累计",
)


def _analysis_recipe_output_signal_name(name: str) -> str:
    return f"{_canonical_metric_name(name)}_score"


def _analysis_recipe_step_tool(
    *,
    metric: str,
    coverage: Mapping[str, Any],
) -> tuple[str, bool]:
    existing_tools = [str(tool) for tool in _ensure_list(coverage.get("existing_tool_ids"))]
    if existing_tools:
        return existing_tools[0], True
    if metric == "unknown_metric" or any(
        keyword in metric for keyword in ANALYSIS_RECIPE_REASONING_STEP_KEYWORDS
    ):
        return ANALYSIS_RECIPE_REASONING_STEP_TOOL, False
    return f"tool.requested.{metric}", True


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
            tool, requires_external_tool = _analysis_recipe_step_tool(
                metric=metric,
                coverage=coverage,
            )
            if requires_external_tool:
                required_tools.append(tool)
            steps.append(
                {
                    "step": index,
                    "tool": tool,
                    "metric": metric,
                    "operation": "candidate_from_report_method",
                    "requires_external_tool": requires_external_tool,
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
    explicit = _normalize_required_data_items(method.get("required_current_data"))
    if explicit:
        return explicit
    inferred_metrics = [
        step.get("metric")
        for step in steps
        if step.get("requires_external_tool") is True
        if str(step.get("metric") or "").strip()
        and str(step.get("metric") or "").strip() != "unknown_metric"
    ]
    if inferred_metrics:
        return _normalize_required_data_items(inferred_metrics)
    return _normalize_required_data_items(ANALYSIS_RECIPE_DEFAULT_REQUIRED_DATA)


def _normalize_required_data_items(value: Any) -> list[str]:
    return normalize_required_data_items(_ensure_list(value))


RECIPE_PAPER_TRADING_PROTOCOL_VERSION = "recipe_shadow_paper_trading_v1"
RECIPE_PAPER_TRADING_MIN_EFFECTIVE_N = 3.0
RECIPE_PAPER_TRADING_MAX_DRAWDOWN = 0.20
RECIPE_PAPER_TRADING_ALPHA_DECAY_FAIL_STREAK = 2
RECIPE_PAPER_TRADING_MAX_HORIZON_CONCENTRATION = 0.70
RECIPE_PAPER_TRADING_MAX_REGIME_CONCENTRATION = 0.80
RECIPE_PAPER_TRADING_MIN_HORIZON_COUNT = 2
RECIPE_PAPER_TRADING_MIN_REGIME_COUNT = 2
RECIPE_PAPER_TRADING_COST_DECAY_TURNOVER_THRESHOLD = 6.0
RECIPE_PAPER_TRADING_OUT_OF_SAMPLE_FRACTION = 0.20
RECIPE_PAPER_TRADING_MIN_OUT_OF_SAMPLE_EFFECTIVE_N = 1.0
RECIPE_PAPER_TRADING_SLIPPAGE_MODEL_ID = "included_in_round_trip_cost_20bps_v1"
RECIPE_PAPER_TRADING_BACKTEST_WINDOW_POLICY = "chronological_pre_oos_exit_windows_v1"
RECIPE_PAPER_TRADING_OUT_OF_SAMPLE_WINDOW_POLICY = (
    "chronological_last_20pct_min_effective_n_exit_windows_v1"
)
RECIPE_PAPER_TRADING_PARAMETER_LOCK_POLICY = (
    "pre_registration_hash_locks_required_data_protocol_cost_benchmark_windows_v1"
)
RECIPE_PAPER_TRADING_BENCHMARK_SYMBOL = STOCK_PRICE_PROXY_BENCHMARK_SYMBOL
RECIPE_PAPER_TRADING_COST_MODEL_ID = STOCK_PRICE_PROXY_COST_MODEL_ID
RECIPE_PAPER_TRADING_INSTABILITY_GAP_BLOCKER = "recipe_instability_gap"
RECIPE_PAPER_TRADING_INSTABILITY_BLOCKERS = (
    "window_horizon_missing",
    "single_window_concentration",
    "market_regime_missing",
    "single_regime_concentration",
)
CONFIDENCE_IMPACT_HIGH_DELTA_THRESHOLD = 0.02
CONFIDENCE_IMPACT_CALIBRATION_ERROR_THRESHOLD = 0.20


def _recipe_paper_trading_protocol() -> dict[str, Any]:
    return {
        "entry_semantics": "T+1_or_more_conservative",
        "exit_semantics": "fixed_horizon_shadow_exit",
        "cost_model_id": RECIPE_PAPER_TRADING_COST_MODEL_ID,
        "benchmark_symbol": RECIPE_PAPER_TRADING_BENCHMARK_SYMBOL,
        "benchmark_source": STOCK_PRICE_PROXY_BENCHMARK_SOURCE,
        "slippage_model_id": RECIPE_PAPER_TRADING_SLIPPAGE_MODEL_ID,
        "round_trip_cost_includes_slippage": True,
        "backtest_window_policy": RECIPE_PAPER_TRADING_BACKTEST_WINDOW_POLICY,
        "out_of_sample_window_policy": (
            RECIPE_PAPER_TRADING_OUT_OF_SAMPLE_WINDOW_POLICY
        ),
        "out_of_sample_fraction": RECIPE_PAPER_TRADING_OUT_OF_SAMPLE_FRACTION,
        "minimum_out_of_sample_effective_n": (
            RECIPE_PAPER_TRADING_MIN_OUT_OF_SAMPLE_EFFECTIVE_N
        ),
        "parameter_lock_policy": RECIPE_PAPER_TRADING_PARAMETER_LOCK_POLICY,
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
        "profile_weight_is_sufficient": False,
        "parameter_tuning_after_results_allowed": False,
        "production_decision_impact_allowed": False,
    }


def _recipe_preregistration_payload(
    *,
    analysis_recipe_id: str,
    promotion_state: str,
    source_method_pattern_ids: Sequence[Any],
    required_tools: Sequence[Any],
    required_data: Sequence[Any],
    decision_scope: str,
    entry_condition: str,
    exit_condition: str,
    risk_controls: Sequence[Any],
    expected_horizon_days: int,
    benchmark_symbol: str,
    benchmark_source: str,
    cost_model_id: str,
    pre_registered_protocol: Mapping[str, Any],
) -> dict[str, Any]:
    payload = {
        "analysis_recipe_id": analysis_recipe_id,
        "promotion_state": promotion_state,
        "protocol_version": RECIPE_PAPER_TRADING_PROTOCOL_VERSION,
        "source_method_pattern_ids": [str(item) for item in source_method_pattern_ids],
        "required_tools": [str(item) for item in required_tools],
        "required_data": _normalize_required_data_items(required_data),
        "decision_scope": decision_scope,
        "entry_condition": entry_condition,
        "exit_condition": exit_condition,
        "risk_controls": [str(item) for item in risk_controls],
        "expected_horizon_days": expected_horizon_days,
        "benchmark_symbol": benchmark_symbol,
        "benchmark_source": benchmark_source,
        "cost_model_id": cost_model_id,
        "pre_registered_protocol": dict(pre_registered_protocol),
        "production_decision_impact_allowed": False,
    }
    return payload


def _recipe_preregistration_hash_from_payload(payload: Mapping[str, Any]) -> str:
    return "sha256:" + sha256(
        json.dumps(
            _jsonable(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _labels_for_recipe(
    recipe: Mapping[str, Any],
    outcome_label_rows: Sequence[Mapping[str, Any]],
    *,
    inferred_labels_by_method_id: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> list[Mapping[str, Any]]:
    recipe_id = str(recipe.get("analysis_recipe_id") or "")
    method_id = str(recipe.get("method_pattern_id") or "")
    source_method_ids = {
        str(item).strip()
        for item in _ensure_list(recipe.get("source_method_pattern_ids"))
        if str(item).strip()
    }
    if method_id:
        source_method_ids.add(method_id)
    labels: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for label in outcome_label_rows:
        if str(label.get("analysis_recipe_id") or "") == recipe_id:
            label_id = str(label.get("outcome_id") or id(label))
            if label_id not in seen:
                labels.append(label)
                seen.add(label_id)
            continue
        if str(label.get("method_pattern_id") or "") in source_method_ids:
            label_id = str(label.get("outcome_id") or id(label))
            if label_id not in seen:
                labels.append(label)
                seen.add(label_id)
    if source_method_ids and inferred_labels_by_method_id:
        for source_method_id in sorted(source_method_ids):
            for label in inferred_labels_by_method_id.get(source_method_id, ()):
                label_id = str(label.get("outcome_id") or id(label))
                if label_id not in seen:
                    labels.append(label)
                    seen.add(label_id)
    return labels


def _inferred_outcome_labels_by_method_id(
    *,
    outcome_label_rows: Sequence[Mapping[str, Any]],
    forecast_rows: Sequence[Mapping[str, Any]],
    footprint_rows: Sequence[Mapping[str, Any]],
    method_rows: Sequence[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    claim_by_id = {
        str(row.get("forecast_claim_id") or ""): row
        for row in forecast_rows
        if str(row.get("forecast_claim_id") or "").strip()
    }
    footprint_by_id = {
        str(row.get("footprint_id") or ""): row
        for row in footprint_rows
        if str(row.get("footprint_id") or "").strip()
    }
    source_methods: dict[str, set[str]] = {}
    report_methods: dict[str, set[str]] = {}
    for method in method_rows:
        method_id = str(method.get("method_pattern_id") or "").strip()
        if not method_id:
            continue
        for footprint_id in _ensure_list(method.get("source_footprint_ids")):
            footprint = footprint_by_id.get(str(footprint_id))
            if not footprint:
                continue
            source_id = str(footprint.get("source_id") or "").strip()
            report_id = str(footprint.get("report_id") or "").strip()
            if source_id:
                source_methods.setdefault(source_id, set()).add(method_id)
            if report_id:
                report_methods.setdefault(report_id, set()).add(method_id)

    labels_by_method: dict[str, list[Mapping[str, Any]]] = {}
    for label in outcome_label_rows:
        if str(label.get("method_pattern_id") or "").strip():
            continue
        claim = claim_by_id.get(str(label.get("forecast_claim_id") or ""))
        if not claim:
            continue
        candidates = set()
        source_id = str(claim.get("source_id") or "").strip()
        report_id = str(claim.get("report_id") or "").strip()
        if source_id:
            candidates.update(source_methods.get(source_id, set()))
        if report_id:
            candidates.update(report_methods.get(report_id, set()))
        if not candidates:
            continue
        for method_id in sorted(candidates):
            labels_by_method.setdefault(method_id, []).append(label)
    return labels_by_method


def _direct_pit_binding_gap_details(
    *,
    analysis_recipe_rows: Sequence[Mapping[str, Any]],
    outcome_label_rows: Sequence[Mapping[str, Any]],
    forecast_rows: Sequence[Mapping[str, Any]],
    footprint_rows: Sequence[Mapping[str, Any]],
    method_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    method_ids = {
        str(row.get("method_pattern_id") or "").strip()
        for row in method_rows
        if str(row.get("method_pattern_id") or "").strip()
    }
    methods_with_source_footprints = {
        str(row.get("method_pattern_id") or "").strip()
        for row in method_rows
        if str(row.get("method_pattern_id") or "").strip()
        and _ensure_list(row.get("source_footprint_ids"))
    }
    footprint_ids = {
        str(row.get("footprint_id") or "").strip()
        for row in footprint_rows
        if str(row.get("footprint_id") or "").strip()
    }
    linked_footprint_ids = {
        str(footprint_id or "").strip()
        for row in method_rows
        for footprint_id in _ensure_list(row.get("source_footprint_ids"))
        if str(footprint_id or "").strip()
    }
    footprints_with_source_or_report = {
        str(row.get("footprint_id") or "").strip()
        for row in footprint_rows
        if str(row.get("footprint_id") or "").strip()
        and (
            str(row.get("source_id") or "").strip()
            or str(row.get("report_id") or "").strip()
        )
    }
    forecast_ids = {
        str(row.get("forecast_claim_id") or "").strip()
        for row in forecast_rows
        if str(row.get("forecast_claim_id") or "").strip()
    }
    forecasts_with_source_or_report = {
        str(row.get("forecast_claim_id") or "").strip()
        for row in forecast_rows
        if str(row.get("forecast_claim_id") or "").strip()
        and (
            str(row.get("source_id") or "").strip()
            or str(row.get("report_id") or "").strip()
        )
    }
    explicit_recipe_label_ids = {
        str(row.get("analysis_recipe_id") or "").strip()
        for row in outcome_label_rows
        if str(row.get("analysis_recipe_id") or "").strip()
    }
    explicit_method_label_ids = {
        str(row.get("method_pattern_id") or "").strip()
        for row in outcome_label_rows
        if str(row.get("method_pattern_id") or "").strip()
    }
    label_forecast_ids = {
        str(row.get("forecast_claim_id") or "").strip()
        for row in outcome_label_rows
        if str(row.get("forecast_claim_id") or "").strip()
    }
    inferred_labels_by_method_id = _inferred_outcome_labels_by_method_id(
        outcome_label_rows=outcome_label_rows,
        forecast_rows=forecast_rows,
        footprint_rows=footprint_rows,
        method_rows=method_rows,
    )
    inferred_method_label_ids = set(inferred_labels_by_method_id)
    recipe_method_ids: set[str] = set()
    recipes_with_source_method_ids = 0
    for recipe in analysis_recipe_rows:
        recipe_methods = {
            str(method_id or "").strip()
            for method_id in _ensure_list(recipe.get("source_method_pattern_ids"))
            if str(method_id or "").strip()
        }
        method_id = str(recipe.get("method_pattern_id") or "").strip()
        if method_id:
            recipe_methods.add(method_id)
        if recipe_methods:
            recipes_with_source_method_ids += 1
        recipe_method_ids.update(recipe_methods)
    method_ids_with_any_label = explicit_method_label_ids | inferred_method_label_ids
    recipes_with_direct_labels: set[str] = set()
    for index, recipe in enumerate(analysis_recipe_rows, 1):
        recipe_id = _recipe_id(recipe, index)
        if recipe_id in explicit_recipe_label_ids:
            recipes_with_direct_labels.add(recipe_id)
            continue
        recipe_methods = {
            str(method_id or "").strip()
            for method_id in _ensure_list(recipe.get("source_method_pattern_ids"))
            if str(method_id or "").strip()
        }
        method_id = str(recipe.get("method_pattern_id") or "").strip()
        if method_id:
            recipe_methods.add(method_id)
        if recipe_methods & method_ids_with_any_label:
            recipes_with_direct_labels.add(recipe_id)
    unresolved_label_forecast_ids = sorted(label_forecast_ids - forecast_ids)
    linked_missing_footprint_ids = sorted(linked_footprint_ids - footprint_ids)
    missing_flags: list[str] = []
    if not outcome_label_rows:
        missing_flags.append("outcome_labels_absent")
    if not forecast_rows:
        missing_flags.append("forecast_claims_absent")
    if not footprint_rows:
        missing_flags.append("analytical_footprints_absent")
    if method_ids and not methods_with_source_footprints:
        missing_flags.append("method_source_footprints_empty")
    if label_forecast_ids and not forecasts_with_source_or_report:
        missing_flags.append("label_forecasts_without_source_or_report")
    return {
        "diagnostic_version": "direct_pit_binding_gap_v1",
        "artifact_counts": {
            "analysis_recipe_rows": len(analysis_recipe_rows),
            "outcome_label_rows": len(outcome_label_rows),
            "forecast_claim_rows": len(forecast_rows),
            "analytical_footprint_rows": len(footprint_rows),
            "method_pattern_rows": len(method_rows),
        },
        "method_source_linkage": {
            "method_pattern_count": len(method_ids),
            "method_patterns_with_source_footprints": len(
                methods_with_source_footprints
            ),
            "method_patterns_without_source_footprints": max(
                0,
                len(method_ids) - len(methods_with_source_footprints),
            ),
            "linked_source_footprint_count": len(linked_footprint_ids),
            "linked_source_footprints_missing_from_footprint_artifact": len(
                linked_missing_footprint_ids
            ),
        },
        "forecast_outcome_linkage": {
            "forecast_claim_count": len(forecast_ids),
            "forecasts_with_source_or_report": len(forecasts_with_source_or_report),
            "outcome_labels_with_forecast_claim_id": len(label_forecast_ids),
            "outcome_label_forecast_ids_missing_from_forecast_artifact": len(
                unresolved_label_forecast_ids
            ),
        },
        "footprint_source_linkage": {
            "analytical_footprint_count": len(footprint_ids),
            "footprints_with_source_or_report": len(footprints_with_source_or_report),
        },
        "recipe_binding_linkage": {
            "recipe_count": len(analysis_recipe_rows),
            "recipes_with_source_method_patterns": recipes_with_source_method_ids,
            "recipe_source_method_pattern_count": len(recipe_method_ids),
            "outcome_labels_with_analysis_recipe_id": len(explicit_recipe_label_ids),
            "outcome_labels_with_method_pattern_id": len(explicit_method_label_ids),
            "inferred_method_pattern_label_count": len(inferred_method_label_ids),
            "recipes_with_direct_or_method_outcome_binding": len(
                recipes_with_direct_labels
            ),
        },
        "missing_artifact_flags": missing_flags,
        "next_actions": [
            "regenerate method patterns with source_footprint_ids preserved",
            "keep forecast claims and analytical footprints available for derived refresh",
            "rebuild PIT outcome labels so labels carry recipe_id or method_pattern_id",
            "rerun recipe paper-trading after direct labels and shadow tools are ready",
        ],
    }


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


def _label_market_regime_types(label: Mapping[str, Any]) -> list[str]:
    explicit = [
        str(item).strip()
        for item in _ensure_list(label.get("market_regime_types"))
        if str(item).strip()
    ]
    if explicit:
        return list(dict.fromkeys(explicit))
    text = str(label.get("market_regime") or label.get("regime") or "").strip()
    if not text:
        return []
    parts = [
        part.strip()
        for part in re.split(r"[|,;，；]", text)
        if part.strip()
    ]
    return list(dict.fromkeys(parts or [text]))


def _paper_trading_effective_weight(
    items: Sequence[Mapping[str, Any]],
) -> float:
    return sum(
        max(_float_or_none(item.get("weight")) or 0.0, 0.0)
        for item in items
    )


def _paper_trading_train_oos_split_items(
    items: Sequence[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    ordered = sorted(items, key=lambda row: str(row.get("exit_datetime") or ""))
    if not ordered:
        return [], []
    oos_count = max(
        1,
        int(
            len(ordered)
            * RECIPE_PAPER_TRADING_OUT_OF_SAMPLE_FRACTION
            + 0.999999
        ),
    )
    split_index = max(0, len(ordered) - oos_count)
    oos_items = list(ordered[split_index:])
    while (
        split_index > 0
        and _paper_trading_effective_weight(oos_items)
        < RECIPE_PAPER_TRADING_MIN_OUT_OF_SAMPLE_EFFECTIVE_N
    ):
        split_index -= 1
        oos_items.insert(0, ordered[split_index])
    return list(ordered[:split_index]), oos_items


def _max_non_positive_after_cost_exit_date_streak(
    items: Sequence[Mapping[str, Any]],
) -> int:
    buckets: dict[str, list[tuple[float, float]]] = {}
    for item in items:
        after_cost = _float_or_none(item.get("after_cost"))
        if after_cost is None:
            continue
        exit_datetime = str(item.get("exit_datetime") or "")
        buckets.setdefault(exit_datetime, []).append(
            (after_cost, max(_float_or_none(item.get("weight")) or 0.0, 0.0))
        )
    max_streak = 0
    current_streak = 0
    for exit_datetime in sorted(buckets):
        date_alpha = _weighted_mean(buckets[exit_datetime], default=None)
        if date_alpha is not None and date_alpha <= 0:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0
    return max_streak


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
    chronological_items: list[dict[str, Any]] = []
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
        hit_value = 1.0 if label.get("directional_hit") is True else 0.0
        weighted_hit.append((hit_value, weight))
        chronological_items.append(
            {
                "exit_datetime": str(label.get("exit_datetime") or ""),
                "after_cost": after_cost,
                "hit": hit_value,
                "weight": weight,
            }
        )
        horizon = _int_or_none(label.get("horizon_days"))
        if horizon:
            horizons.append(horizon)
            horizon_key = str(horizon)
            horizon_weight_totals[horizon_key] = (
                horizon_weight_totals.get(horizon_key, 0.0) + weight
            )
        else:
            horizon_missing_count += 1
        regimes = _label_market_regime_types(label)
        if regimes:
            regime_weight = weight / len(regimes)
            for regime in regimes:
                regime_weight_totals[regime] = (
                    regime_weight_totals.get(regime, 0.0) + regime_weight
                )
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
    max_non_positive_streak = _max_non_positive_after_cost_exit_date_streak(
        chronological_items
    )
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
    backtest_items, oos_items = _paper_trading_train_oos_split_items(
        chronological_items
    )
    backtest_metrics = _paper_trading_chronological_split_metrics(backtest_items)
    oos_metrics = _paper_trading_chronological_split_metrics(oos_items)
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
        "market_regime_coverage_status": (
            "missing_diagnostic_only"
            if market_regime_missing_count and not regime_contribution_shares
            else "partially_missing"
            if market_regime_missing_count
            else "observed"
        ),
        "drawdown_breach_count": sum(
            1
            for value in alpha_values
            if value <= -RECIPE_PAPER_TRADING_MAX_DRAWDOWN
        ),
        "backtest_label_count": backtest_metrics["label_count"],
        "backtest_effective_n": backtest_metrics["effective_n"],
        "backtest_cost_adjusted_alpha": backtest_metrics["cost_adjusted_alpha"],
        "backtest_hit_rate": backtest_metrics["hit_rate"],
        "backtest_start_exit_datetime": backtest_metrics["start_exit_datetime"],
        "backtest_end_exit_datetime": backtest_metrics["end_exit_datetime"],
        "out_of_sample_label_count": oos_metrics["label_count"],
        "out_of_sample_effective_n": oos_metrics["effective_n"],
        "out_of_sample_cost_adjusted_alpha": oos_metrics["cost_adjusted_alpha"],
        "out_of_sample_hit_rate": oos_metrics["hit_rate"],
        "out_of_sample_start_exit_datetime": oos_metrics["start_exit_datetime"],
        "out_of_sample_end_exit_datetime": oos_metrics["end_exit_datetime"],
    }


def _paper_trading_chronological_split_metrics(
    items: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    ordered_items = sorted(items, key=lambda row: str(row.get("exit_datetime") or ""))
    weighted_after_cost = [
        (float(item["after_cost"]), float(item["weight"]))
        for item in ordered_items
        if _float_or_none(item.get("after_cost")) is not None
    ]
    weighted_hit = [
        (float(item["hit"]), float(item["weight"]))
        for item in ordered_items
        if _float_or_none(item.get("hit")) is not None
    ]
    cost_adjusted_alpha = _weighted_mean(weighted_after_cost, default=None)
    hit_rate = _weighted_mean(weighted_hit, default=None)
    effective_n = sum(
        max(_float_or_none(item.get("weight")) or 0.0, 0.0)
        for item in ordered_items
    )
    exit_datetimes = [
        str(item.get("exit_datetime") or "")
        for item in ordered_items
        if str(item.get("exit_datetime") or "").strip()
    ]
    return {
        "label_count": len(ordered_items),
        "effective_n": round(effective_n, 6),
        "cost_adjusted_alpha": round(cost_adjusted_alpha, 8)
        if cost_adjusted_alpha is not None
        else None,
        "hit_rate": round(hit_rate, 6) if hit_rate is not None else None,
        "start_exit_datetime": exit_datetimes[0] if exit_datetimes else "",
        "end_exit_datetime": exit_datetimes[-1] if exit_datetimes else "",
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
    forecast_rows: Sequence[Mapping[str, Any]] = (),
    footprint_rows: Sequence[Mapping[str, Any]] = (),
    method_rows: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    method_profiles = _method_profile_by_method_id(method_performance_profile_rows)
    inferred_labels_by_method_id = _inferred_outcome_labels_by_method_id(
        outcome_label_rows=outcome_label_rows,
        forecast_rows=forecast_rows,
        footprint_rows=footprint_rows,
        method_rows=method_rows,
    )
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
        labels = _labels_for_recipe(
            recipe,
            outcome_label_rows,
            inferred_labels_by_method_id=inferred_labels_by_method_id,
        )
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
        required_data = _normalize_required_data_items(recipe.get("required_data"))
        if not required_data:
            blockers.append("required_data_missing")
        if str(recipe.get("runtime_mode") or "") != "shadow_only":
            blockers.append("unsupported_runtime_mode")
        required_tools = _ensure_list(recipe.get("required_tools"))
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
            out_of_sample_effective_n = _float_or_none(
                metrics.get("out_of_sample_effective_n")
            )
            out_of_sample_alpha = _float_or_none(
                metrics.get("out_of_sample_cost_adjusted_alpha")
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
            if market_regime_missing_count and observed_regime_count > 0:
                blockers.append("market_regime_missing")
            if observed_regime_count > 0 and (
                observed_regime_count < RECIPE_PAPER_TRADING_MIN_REGIME_COUNT
                or (
                    max_regime_share is not None
                    and max_regime_share
                    > RECIPE_PAPER_TRADING_MAX_REGIME_CONCENTRATION
                )
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
            if (
                out_of_sample_effective_n is None
                or out_of_sample_effective_n
                < RECIPE_PAPER_TRADING_MIN_OUT_OF_SAMPLE_EFFECTIVE_N
            ):
                blockers.append("out_of_sample_effective_n_below_threshold")
            if out_of_sample_alpha is None or out_of_sample_alpha <= 0:
                blockers.append("out_of_sample_after_cost_alpha_non_positive")
        if any(
            reason in RECIPE_PAPER_TRADING_INSTABILITY_BLOCKERS
            for reason in blockers
        ):
            blockers.append(RECIPE_PAPER_TRADING_INSTABILITY_GAP_BLOCKER)
        method_profile = method_profiles.get(method_id) or {}
        profile_n = _float_or_none(
            _ensure_mapping(method_profile.get("source_support")).get(
                "n_effective_reports"
            )
        )
        profile_support_only = (profile_n or 0.0) > 0 and bool(blockers)
        status = "passed" if not blockers else "blocked"
        pre_registered_protocol = _recipe_paper_trading_protocol()
        pre_registration_hash = _recipe_preregistration_hash_from_payload(
            _recipe_preregistration_payload(
                analysis_recipe_id=recipe_id,
                promotion_state="shadow_candidate",
                source_method_pattern_ids=source_method_pattern_ids,
                required_tools=required_tools,
                required_data=required_data,
                decision_scope=decision_scope,
                entry_condition=entry_condition,
                exit_condition=exit_condition,
                risk_controls=risk_controls,
                expected_horizon_days=expected_horizon_days,
                benchmark_symbol=RECIPE_PAPER_TRADING_BENCHMARK_SYMBOL,
                benchmark_source=STOCK_PRICE_PROXY_BENCHMARK_SOURCE,
                cost_model_id=RECIPE_PAPER_TRADING_COST_MODEL_ID,
                pre_registered_protocol=pre_registered_protocol,
            )
        )
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
                "pre_registration_hash": pre_registration_hash,
                "protocol_version": RECIPE_PAPER_TRADING_PROTOCOL_VERSION,
                "promotion_state": "shadow_candidate",
                "validation_status": status,
                "paper_trading_status": status,
                "source_method_pattern_ids": source_method_pattern_ids,
                "required_tools": required_tools,
                "required_data": required_data,
                "decision_scope": decision_scope,
                "entry_condition": entry_condition,
                "exit_condition": exit_condition,
                "risk_controls": risk_controls,
                "expected_horizon_days": expected_horizon_days,
                "benchmark_symbol": RECIPE_PAPER_TRADING_BENCHMARK_SYMBOL,
                "benchmark_source": STOCK_PRICE_PROXY_BENCHMARK_SOURCE,
                "cost_model_id": RECIPE_PAPER_TRADING_COST_MODEL_ID,
                "pre_registered_protocol": pre_registered_protocol,
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
    tool_gap_rows: Sequence[Mapping[str, Any]] = (),
    tool_design_proposal_rows: Sequence[Mapping[str, Any]] = (),
    direct_pit_binding_gap_details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    blocker_counts: dict[str, int] = {}
    passed_ids: list[str] = []
    blocked_ids: list[str] = []
    disagreement_count = 0
    instability_gap_count = 0
    cost_adjusted_values: list[float] = []
    passed_cost_adjusted_values: list[float] = []
    direct_pit_bound_ids: list[str] = []
    direct_pit_bound_blocker_counts: dict[str, int] = {}
    validation_candidate_ids: list[str] = []
    tool_only_blocked_ids: list[str] = []
    tool_gap_ids_by_method_id: dict[str, list[str]] = {}
    tool_gap_ids: set[str] = set()
    queued_tool_gap_ids: set[str] = set()
    queued_tool_proposal_ids: set[str] = set()
    queued_requested_tools: set[str] = set()
    queued_recipe_ids: set[str] = set()
    for gap in tool_gap_rows:
        gap_id = str(gap.get("tool_gap_id") or "").strip()
        if not gap_id or str(gap.get("status") or "") == "retired":
            continue
        tool_gap_ids.add(gap_id)
        for method_id in _ensure_list(gap.get("method_pattern_ids")):
            method_key = str(method_id or "").strip()
            if method_key:
                tool_gap_ids_by_method_id.setdefault(method_key, []).append(gap_id)
    proposal_ids_by_gap_id: dict[str, list[str]] = {}
    for proposal in tool_design_proposal_rows:
        gap_id = str(proposal.get("tool_gap_id") or "").strip()
        proposal_id = str(proposal.get("tool_proposal_id") or "").strip()
        if gap_id and proposal_id:
            proposal_ids_by_gap_id.setdefault(gap_id, []).append(proposal_id)
    tool_only_gap_ids: set[str] = set()
    tool_only_proposal_ids: set[str] = set()
    for run in recipe_paper_trading_runs:
        status = str(run.get("paper_trading_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        recipe_id = str(run.get("analysis_recipe_id") or "")
        metrics = _ensure_mapping(run.get("metrics"))
        effective_n = _float_or_none(metrics.get("effective_n")) or 0.0
        blocked_reasons = [str(reason) for reason in _ensure_list(run.get("blocked_reasons"))]
        direct_pit_bound = effective_n > 0.0 and "no_direct_recipe_outcome_binding" not in blocked_reasons
        if direct_pit_bound:
            direct_pit_bound_ids.append(recipe_id)
            for reason in blocked_reasons:
                _increment_count(direct_pit_bound_blocker_counts, reason)
        if direct_pit_bound and "insufficient_effective_n" not in blocked_reasons:
            validation_candidate_ids.append(recipe_id)
        if blocked_reasons == ["required_tools_not_shadow_implemented"]:
            tool_only_blocked_ids.append(recipe_id)
            for method_id in _ensure_list(run.get("source_method_pattern_ids")):
                for gap_id in tool_gap_ids_by_method_id.get(str(method_id or ""), ()):
                    tool_only_gap_ids.add(gap_id)
                    tool_only_proposal_ids.update(proposal_ids_by_gap_id.get(gap_id, ()))
        if "required_tools_not_shadow_implemented" in blocked_reasons:
            queued_recipe_ids.add(recipe_id)
            for tool in _ensure_list(run.get("required_tools")):
                tool_name = str(tool or "").strip()
                if tool_name.startswith("tool.requested."):
                    queued_requested_tools.add(tool_name)
            for method_id in _ensure_list(run.get("source_method_pattern_ids")):
                for gap_id in tool_gap_ids_by_method_id.get(str(method_id or ""), ()):
                    queued_tool_gap_ids.add(gap_id)
                    queued_tool_proposal_ids.update(
                        proposal_ids_by_gap_id.get(gap_id, ())
                    )
        if status == "passed":
            passed_ids.append(recipe_id)
        else:
            blocked_ids.append(recipe_id)
        for reason in blocked_reasons:
            _increment_count(blocker_counts, reason)
            if reason == RECIPE_PAPER_TRADING_INSTABILITY_GAP_BLOCKER:
                instability_gap_count += 1
        profile_support = _ensure_mapping(run.get("profile_weight_support"))
        if profile_support.get("profile_paper_trade_disagreement") is True:
            disagreement_count += 1
        cost_adjusted = _float_or_none(
            _ensure_mapping(run.get("metrics")).get("cost_adjusted_alpha")
        )
        if cost_adjusted is not None:
            cost_adjusted_values.append(cost_adjusted)
            if status == "passed":
                passed_cost_adjusted_values.append(cost_adjusted)
    passed_cost_adjusted_values = sorted(passed_cost_adjusted_values)
    passed_count = len(passed_cost_adjusted_values)
    if passed_count:
        midpoint = passed_count // 2
        if passed_count % 2:
            median_after_cost_alpha: float | None = passed_cost_adjusted_values[
                midpoint
            ]
        else:
            median_after_cost_alpha = (
                passed_cost_adjusted_values[midpoint - 1]
                + passed_cost_adjusted_values[midpoint]
            ) / 2.0
        after_cost_paper_trading_summary = {
            "status": "computed",
            "validated_recipe_count": passed_count,
            "mean_after_cost_alpha": round(
                sum(passed_cost_adjusted_values) / passed_count,
                8,
            ),
            "median_after_cost_alpha": round(median_after_cost_alpha, 8),
            "min_after_cost_alpha": round(min(passed_cost_adjusted_values), 8),
            "max_after_cost_alpha": round(max(passed_cost_adjusted_values), 8),
            "positive_after_cost_recipe_count": sum(
                1 for value in passed_cost_adjusted_values if value > 0
            ),
            "policy": (
                "computed from passed pre-registered paper-trading runs only; "
                "blocked or profile-only recipes are excluded"
            ),
        }
    else:
        after_cost_paper_trading_summary = {
            "status": "insufficient_validated_runs",
            "validated_recipe_count": 0,
            "mean_after_cost_alpha": None,
            "median_after_cost_alpha": None,
            "min_after_cost_alpha": None,
            "max_after_cost_alpha": None,
            "positive_after_cost_recipe_count": 0,
            "policy": (
                "computed from passed pre-registered paper-trading runs only; "
                "blocked or profile-only recipes are excluded"
            ),
        }
    direct_pit_gap_count = int(
        blocker_counts.get("no_direct_recipe_outcome_binding", 0)
    )
    insufficient_effective_n_count = int(
        blocker_counts.get("insufficient_effective_n", 0)
    )
    requested_tool_block_count = int(
        blocker_counts.get("required_tools_not_shadow_implemented", 0)
    )
    direct_pit_binding_status = (
        "ready_for_validation"
        if (
            not direct_pit_gap_count
            and direct_pit_bound_ids
            and not insufficient_effective_n_count
            and not requested_tool_block_count
        )
        else "partial_direct_pit_binding"
        if direct_pit_bound_ids
        else "blocked_no_direct_pit_binding"
    )
    direct_pit_binding_next_actions: list[str] = []
    if direct_pit_gap_count:
        direct_pit_binding_next_actions.append(
            "link recipes to source-grounded method patterns and PIT outcome labels"
        )
    if insufficient_effective_n_count:
        direct_pit_binding_next_actions.append(
            "expand direct PIT-bound outcome samples until effective_n passes"
        )
    if requested_tool_block_count:
        direct_pit_binding_next_actions.append(
            "implement or reject requested shadow tools before validation"
        )
    if not direct_pit_binding_next_actions:
        direct_pit_binding_next_actions.append("monitor validated paper-trading drift")
    direct_pit_binding_diagnostics: dict[str, Any] = {
        "status": direct_pit_binding_status,
        "diagnostic_only": True,
        "policy": (
            "profile weights and method names are insufficient; recipe "
            "paper-trading requires direct PIT outcome labels bound to the "
            "recipe or its source method pattern"
        ),
        "recipe_count": len(recipe_paper_trading_runs),
        "direct_pit_bound_recipe_count": len(direct_pit_bound_ids),
        "no_direct_recipe_outcome_binding_count": direct_pit_gap_count,
        "insufficient_effective_n_count": insufficient_effective_n_count,
        "required_tools_not_shadow_implemented_count": requested_tool_block_count,
        "next_actions": direct_pit_binding_next_actions,
    }
    if direct_pit_binding_gap_details:
        direct_pit_binding_diagnostics["binding_gap_details"] = dict(
            direct_pit_binding_gap_details
        )
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
        "direct_pit_bound_recipe_count": len(direct_pit_bound_ids),
        "direct_pit_bound_recipe_ids": sorted(direct_pit_bound_ids),
        "direct_pit_bound_blocker_counts": dict(
            sorted(direct_pit_bound_blocker_counts.items())
        ),
        "direct_pit_binding_diagnostics": direct_pit_binding_diagnostics,
        "validation_candidate_recipe_count": len(validation_candidate_ids),
        "validation_candidate_recipe_ids": sorted(validation_candidate_ids),
        "tool_only_blocked_recipe_count": len(tool_only_blocked_ids),
        "tool_only_blocked_recipe_ids": sorted(tool_only_blocked_ids),
        "tool_only_blocked_tool_gap_count": len(tool_only_gap_ids),
        "tool_only_blocked_tool_gap_ids": sorted(tool_only_gap_ids),
        "tool_only_blocked_tool_proposal_count": len(tool_only_proposal_ids),
        "tool_only_blocked_tool_proposal_ids": sorted(tool_only_proposal_ids),
        "tool_implementation_queue": {
            "queue_policy": (
                "implement or explicitly reject tool gaps linked to direct-PIT "
                "validation candidates before promoting recipe confidence impact"
            ),
            "source_blocker": "required_tools_not_shadow_implemented",
            "blocked_recipe_count": len(queued_recipe_ids),
            "blocked_recipe_ids": sorted(queued_recipe_ids),
            "requested_tool_count": len(queued_requested_tools),
            "requested_tools": sorted(queued_requested_tools),
            "tool_gap_count": len(queued_tool_gap_ids),
            "tool_gap_ids": sorted(queued_tool_gap_ids),
            "tool_proposal_count": len(queued_tool_proposal_ids),
            "tool_proposal_ids": sorted(queued_tool_proposal_ids),
            "unlinked_tool_gap_registry_count": max(
                0,
                len(tool_gap_ids - queued_tool_gap_ids),
            ),
            "unlinked_requested_tool_count": max(
                0,
                len(queued_requested_tools) - len(queued_tool_gap_ids),
            ),
        },
        "profile_paper_trade_disagreement_count": disagreement_count,
        "recipe_instability_gap_count": instability_gap_count,
        "mean_cost_adjusted_alpha": round(
            sum(cost_adjusted_values) / len(cost_adjusted_values),
            8,
        )
        if cost_adjusted_values
        else None,
        "after_cost_paper_trading_summary": after_cost_paper_trading_summary,
        "minimum_effective_n": RECIPE_PAPER_TRADING_MIN_EFFECTIVE_N,
        "pre_registration_policy": (
            "each recipe has a deterministic experiment id and pre-registration hash "
            "before any outcome metrics are evaluated"
        ),
        "validation_protocol": _recipe_paper_trading_protocol(),
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
        regime_contribution_shares = {
            str(key): float(value)
            for key, value in _ensure_mapping(
                metrics.get("regime_contribution_shares")
            ).items()
            if _float_or_none(value) is not None
        }
        dominant_regime = "unknown"
        if regime_contribution_shares:
            dominant_regime = sorted(
                regime_contribution_shares.items(),
                key=lambda item: (-item[1], item[0]),
            )[0][0]
        market_regime_coverage_status = str(
            metrics.get("market_regime_coverage_status") or "unknown"
        )
        blocker_reasons = _ensure_list(run.get("blocked_reasons"))
        profile_support = _ensure_mapping(run.get("profile_weight_support"))
        profile_paper_trade_disagreement = (
            profile_support.get("profile_paper_trade_disagreement") is True
        )
        alpha_decay_blockers = {
            "after_cost_alpha_non_positive",
            "consecutive_non_positive_after_cost_windows",
            "max_drawdown_breach",
        }
        cost_decay_blockers = {"cost_decay_fail"}
        regime_fragile_blockers = set(RECIPE_PAPER_TRADING_INSTABILITY_BLOCKERS) | {
            RECIPE_PAPER_TRADING_INSTABILITY_GAP_BLOCKER
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
        elif paper_status != "passed" and profile_paper_trade_disagreement:
            drift_status = "profile_paper_trade_disagreement"
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
                "regime": dominant_regime,
                "regime_status": (
                    "dominant_observed"
                    if dominant_regime != "unknown"
                    else "missing_diagnostic"
                ),
                "regime_contribution_shares": regime_contribution_shares,
                "max_regime_contribution_share": metrics.get(
                    "max_regime_contribution_share"
                ),
                "observed_regime_count": metrics.get("observed_regime_count"),
                "market_regime_missing_count": metrics.get(
                    "market_regime_missing_count"
                ),
                "market_regime_coverage_status": market_regime_coverage_status,
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
    profile_paper_trade_disagreement_recipe_ids: list[str] = []
    manual_review_recipe_ids: list[str] = []
    reduce_confidence_impact_recipe_ids: list[str] = []
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
        if (
            str(row.get("drift_status") or "")
            == "profile_paper_trade_disagreement"
            and recipe_id
        ):
            profile_paper_trade_disagreement_recipe_ids.append(recipe_id)
        action = str(row.get("recommended_action") or "")
        if action == "reduce_confidence_impact" and recipe_id:
            reduce_confidence_impact_recipe_ids.append(recipe_id)
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
        "profile_paper_trade_disagreement_count": drift_status_counts.get(
            "profile_paper_trade_disagreement",
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
        "profile_paper_trade_disagreement_recipe_ids": sorted(
            set(profile_paper_trade_disagreement_recipe_ids)
        ),
        "manual_review_recipe_ids": sorted(set(manual_review_recipe_ids)),
        "reduce_confidence_impact_recipe_ids": sorted(
            set(reduce_confidence_impact_recipe_ids)
        ),
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
    forecast_rows: list[Mapping[str, Any]] = []
    forecast_path = registry_path / "forecast_claims.jsonl"
    if forecast_path.exists():
        forecast_rows = _read_registry_jsonl(
            forecast_path,
            label="forecast_claims",
            blockers=blockers,
        )
    footprint_rows: list[Mapping[str, Any]] = []
    footprint_path = registry_path / "analytical_footprints.jsonl"
    if footprint_path.exists():
        footprint_rows = _read_registry_jsonl(
            footprint_path,
            label="analytical_footprints",
            blockers=blockers,
        )
    method_rows: list[Mapping[str, Any]] = []
    method_path = registry_path / "method_patterns.jsonl"
    if method_path.exists():
        method_rows = _read_registry_jsonl(
            method_path,
            label="method_patterns",
            blockers=blockers,
        )
    tool_gap_rows: list[Mapping[str, Any]] = []
    tool_gap_path = registry_path / "tool_gaps.jsonl"
    if tool_gap_path.exists():
        tool_gap_rows = _read_registry_jsonl(
            tool_gap_path,
            label="tool_gaps",
            blockers=blockers,
        )
    tool_design_proposal_rows: list[Mapping[str, Any]] = []
    tool_design_proposal_path = registry_path / "tool_design_proposals.jsonl"
    if tool_design_proposal_path.exists():
        tool_design_proposal_rows = _read_registry_jsonl(
            tool_design_proposal_path,
            label="tool_design_proposals",
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
        forecast_rows=forecast_rows,
        footprint_rows=footprint_rows,
        method_rows=method_rows,
    )
    recipe_paper_trading_summary = build_recipe_paper_trading_summary(
        run_id=run_id,
        recipe_paper_trading_runs=recipe_paper_trading_run_rows,
        tool_gap_rows=tool_gap_rows,
        tool_design_proposal_rows=tool_design_proposal_rows,
        direct_pit_binding_gap_details=_direct_pit_binding_gap_details(
            analysis_recipe_rows=analysis_recipe_rows,
            outcome_label_rows=outcome_label_rows,
            forecast_rows=forecast_rows,
            footprint_rows=footprint_rows,
            method_rows=method_rows,
        ),
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


def _gold_review_metric(
    gold: Mapping[str, Any],
    metrics: Mapping[str, Any],
    field: str,
) -> float | None:
    value = metrics.get(field)
    if value is None:
        value = gold.get(field)
    return _float_or_none(value)


def _forecast_gold_review_gate(
    *,
    gold_review_summary: Mapping[str, Any],
    outcome_labeling_readiness: Mapping[str, Any] | None,
) -> tuple[bool, dict[str, Any], list[str]]:
    gold = _ensure_mapping(gold_review_summary)
    metrics = _ensure_mapping(gold.get("metrics"))
    readiness = _ensure_mapping(outcome_labeling_readiness)
    stock_readiness = _ensure_mapping(readiness.get("stock_price_proxy_readiness"))
    stock_gap_counts = _count_mapping_values(
        _ensure_mapping(stock_readiness.get("data_gap_counts"))
    )
    blockers: list[str] = []
    summary_passed = gold.get("passed") is True or gold.get("accepted") is True
    review_complete = gold.get("review_complete") is True
    reviewed_claims = int(gold.get("reviewed_claims") or 0)
    total_documents = int(gold.get("total_documents") or 0)
    pending_claims = int(gold.get("pending_claims") or 0)
    if not summary_passed:
        blockers.append("forecast_gold_set_gate_not_passed")
    if not review_complete:
        blockers.append("forecast_gold_set_review_incomplete")
    if reviewed_claims < FORECAST_GOLD_MIN_REVIEWED_CLAIMS:
        blockers.append("gold_reviewed_claims_below_threshold")
    if total_documents < FORECAST_GOLD_MIN_DOCUMENTS:
        blockers.append("gold_reviewed_documents_below_threshold")
    if pending_claims:
        blockers.append("gold_pending_claims_remaining")
    metric_values: dict[str, float | None] = {}
    for field, threshold in FORECAST_GOLD_REVIEW_MIN_METRICS.items():
        value = _gold_review_metric(gold, metrics, field)
        metric_values[field] = value
        if value is None:
            blockers.append(f"{field}_missing")
        elif value < threshold:
            blockers.append(f"{field}_below_threshold")
    for field, threshold in FORECAST_GOLD_REVIEW_MAX_METRICS.items():
        value = _gold_review_metric(gold, metrics, field)
        metric_values[field] = value
        if value is None:
            blockers.append(f"{field}_missing")
        elif value > threshold:
            blockers.append(f"{field}_above_threshold")
    stock_target_conflict_count = int(stock_gap_counts.get("stock_target_conflict") or 0)
    conflict_reviewed_count = int(
        gold.get("stock_target_conflict_reviewed_count")
        or metrics.get("stock_target_conflict_reviewed_count")
        or 0
    )
    stock_target_conflict_explained = (
        gold.get("stock_target_conflict_explained") is True
        or metrics.get("stock_target_conflict_explained") is True
        or (
            stock_target_conflict_count > 0
            and conflict_reviewed_count >= stock_target_conflict_count
        )
    )
    if stock_target_conflict_count and not stock_target_conflict_explained:
        blockers.append("stock_target_conflict_unexplained")
    evidence = {
        "gold_set_passed": not blockers,
        "review_complete": review_complete,
        "reviewed_claims": reviewed_claims,
        "pending_claims": pending_claims,
        "total_documents": total_documents,
        "metrics": metric_values,
        "thresholds": {
            "min_reviewed_claims": FORECAST_GOLD_MIN_REVIEWED_CLAIMS,
            "min_documents": FORECAST_GOLD_MIN_DOCUMENTS,
            **{
                f"{field}_min": threshold
                for field, threshold in FORECAST_GOLD_REVIEW_MIN_METRICS.items()
            },
            **{
                f"{field}_max": threshold
                for field, threshold in FORECAST_GOLD_REVIEW_MAX_METRICS.items()
            },
        },
        "stock_target_conflict_count": stock_target_conflict_count,
        "stock_target_conflict_reviewed_count": conflict_reviewed_count,
        "stock_target_conflict_explained": stock_target_conflict_explained,
    }
    return not blockers, evidence, blockers


def _evolution_gate_requirement_shortfalls(
    checks: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    by_id = {
        str(check.get("check_id") or ""): _ensure_mapping(check) for check in checks
    }
    shortfalls: dict[str, Any] = {}

    outcome_evidence = _ensure_mapping(by_id.get("RI-EVOL-01", {}).get("evidence"))
    shortfalls["unique_outcome_claim_count"] = _threshold_shortfall(
        current=int(outcome_evidence.get("unique_outcome_claim_count") or 0),
        target=EVOLUTION_GATE_MIN_UNIQUE_OUTCOME_CLAIMS,
        blocker="unique_outcome_claim_count_below_threshold",
        next_action="produce_more_non_llm_pit_outcome_labels",
    )
    shortfalls["stock_proxy_unique_claim_count"] = _threshold_shortfall(
        current=int(outcome_evidence.get("stock_proxy_unique_claim_count") or 0),
        target=EVOLUTION_GATE_MIN_STOCK_PROXY_CLAIMS,
        blocker="stock_proxy_claim_count_below_threshold",
        next_action="run_stock_price_proxy_labels_for_historical_stock_reports",
    )
    shortfalls["industry_proxy_unique_claim_count"] = _threshold_shortfall(
        current=int(outcome_evidence.get("industry_proxy_unique_claim_count") or 0),
        target=EVOLUTION_GATE_MIN_INDUSTRY_PROXY_CLAIMS,
        blocker="industry_proxy_claim_count_below_threshold",
        next_action="run_industry_etf_proxy_labels_for_mapped_industry_reports",
    )

    paper_evidence = _ensure_mapping(by_id.get("RI-EVOL-02", {}).get("evidence"))
    shortfalls["paper_trading_run_count"] = _threshold_shortfall(
        current=int(paper_evidence.get("paper_trading_run_count") or 0),
        target=EVOLUTION_GATE_MIN_PAPER_TRADING_RECIPES,
        blocker="paper_trading_run_count_below_threshold",
        next_action="pre_register_more_analysis_recipes_for_shadow_paper_trading",
    )
    shortfalls["paper_trading_validated_recipe_count"] = _threshold_shortfall(
        current=int(paper_evidence.get("validation_pass_count") or 0),
        target=EVOLUTION_GATE_MIN_PAPER_TRADING_RECIPES,
        blocker="paper_trading_validated_recipe_count_below_threshold",
        next_action="bind_recipe_runs_to_direct_pit_outcomes_and_after_cost_metrics",
    )
    after_cost_summary = _ensure_mapping(
        paper_evidence.get("after_cost_paper_trading_summary")
    )
    after_cost_summary_status = str(after_cost_summary.get("status") or "").strip()
    shortfalls["after_cost_paper_trading_summary"] = {
        "status": after_cost_summary_status or "missing",
        "blocker": (
            "after_cost_paper_trading_summary_missing"
            if not after_cost_summary_status
            else ""
        ),
        "next_action": (
            "compute_mean_after_cost_alpha_from_validated_recipe_runs"
            if not after_cost_summary_status
            else "increase_validated_recipe_count_until_after_cost_summary_is_computed"
        ),
    }

    monitor_evidence = _ensure_mapping(by_id.get("RI-EVOL-03", {}).get("evidence"))
    monitor_global_blocker_count = (
        int(monitor_evidence.get("unvalidated_confidence_impact_count") or 0)
        + int(monitor_evidence.get("aggregate_calibration_drift_count") or 0)
        + sum(
            _count_mapping_values(
                _ensure_mapping(monitor_evidence.get("calibration_drift_rule_counts"))
            ).values()
        )
    )
    shortfalls["monitor_distinct_vintage_count"] = _threshold_shortfall(
        current=int(
            monitor_evidence.get("trailing_monitor_distinct_vintage_count") or 0
        ),
        target=EVOLUTION_GATE_MIN_CONSECUTIVE_MONITOR_REFRESHES,
        blocker="confidence_impact_monitor_history_below_threshold",
        next_action=(
            "refresh_distinct_data_vintages_until_monitor_gate_passes_three_times"
        ),
    )
    shortfalls["monitor_current_global_blocker_count"] = {
        "current": monitor_global_blocker_count,
        "target": 0,
        "remaining": monitor_global_blocker_count,
        "blocker": "confidence_impact_monitor_current_blocked",
        "next_action": "clear_unvalidated_confidence_impact_or_aggregate_calibration_drift_before_evolution",
    }

    audit_evidence = _ensure_mapping(by_id.get("RI-EVOL-04", {}).get("evidence"))
    audit_dependency = _ensure_mapping(
        audit_evidence.get("audit_history_dependency")
    )
    audit_next_action = str(audit_dependency.get("next_action") or "").strip() or (
        "refresh_distinct_data_vintages_until_schema_pit_provenance_"
        "statistical_audits_pass_three_times"
    )
    shortfalls["audit_distinct_vintage_count"] = _threshold_shortfall(
        current=int(audit_evidence.get("trailing_audit_distinct_vintage_count") or 0),
        target=EVOLUTION_GATE_MIN_CONSECUTIVE_AUDIT_REFRESHES,
        blocker="audit_refresh_history_below_threshold",
        next_action=audit_next_action,
    )

    gold_evidence = _ensure_mapping(by_id.get("RI-EVOL-05", {}).get("evidence"))
    gold_thresholds = _ensure_mapping(gold_evidence.get("thresholds"))
    metrics = _ensure_mapping(gold_evidence.get("metrics"))
    shortfalls["gold_reviewed_claims"] = _threshold_shortfall(
        current=int(gold_evidence.get("reviewed_claims") or 0),
        target=int(gold_thresholds.get("min_reviewed_claims") or 0),
        blocker="gold_reviewed_claims_below_threshold",
        next_action="complete_manual_forecast_claim_gold_review",
    )
    pending_claims = int(gold_evidence.get("pending_claims") or 0)
    shortfalls["gold_pending_claims"] = {
        "current": pending_claims,
        "target": 0,
        "remaining": pending_claims,
        "blocker": "gold_pending_claims_remaining",
        "next_action": "review_or_exclude_pending_gold_claims",
    }
    metric_gaps: list[str] = []
    for key, raw_value in sorted(metrics.items()):
        value = _float_or_none(raw_value)
        if key == "unsupported_field_false_grounding_rate":
            threshold = _float_or_none(
                gold_thresholds.get("unsupported_field_false_grounding_rate_max")
            )
            if value is None or (threshold is not None and value > threshold):
                metric_gaps.append(key)
            continue
        threshold = _float_or_none(gold_thresholds.get(f"{key}_min"))
        if value is None or (threshold is not None and value < threshold):
            metric_gaps.append(key)
    shortfalls["gold_quality_metric_gaps"] = {
        "missing_or_below_threshold": metric_gaps,
        "blocker": "forecast_gold_set_gate_not_passed",
        "next_action": "raise_manual_review_precision_accuracy_and_grounding_metrics",
    }

    gap_evidence = _ensure_mapping(by_id.get("RI-EVOL-06", {}).get("evidence"))
    shortfalls["gap_distribution_distinct_vintage_count"] = _threshold_shortfall(
        current=int(
            gap_evidence.get("trailing_gap_distribution_distinct_vintage_count") or 0
        ),
        target=EVOLUTION_GATE_MIN_GAP_DISTRIBUTION_REFRESHES,
        blocker="gap_distribution_history_below_threshold",
        next_action="refresh_distinct_data_vintages_until_gap_distribution_is_stable",
    )

    markdown_evidence = _ensure_mapping(by_id.get("RI-EVOL-07", {}).get("evidence"))
    coverage_shortfalls = _ensure_mapping(markdown_evidence.get("coverage_shortfalls"))
    shortfalls["markdown_coverage"] = coverage_shortfalls
    return shortfalls


EVOLUTION_DATA_VINTAGE_HASH_RE = re.compile(r"sha256:[0-9a-f]{64}")


def _valid_data_vintage_hash(value: Any) -> bool:
    return bool(EVOLUTION_DATA_VINTAGE_HASH_RE.fullmatch(str(value or "").strip()))


def _history_vintage_key(row: Mapping[str, Any]) -> str:
    data_vintage_hash = str(row.get("data_vintage_hash") or "").strip()
    if _valid_data_vintage_hash(data_vintage_hash):
        return data_vintage_hash
    return "legacy-unvintaged"


def _evolution_data_vintage_hash(
    *,
    forecast_rows: Sequence[Mapping[str, Any]],
    outcome_label_rows: Sequence[Mapping[str, Any]],
    recipe_paper_trading_summary: Mapping[str, Any],
    confidence_impact_monitor: Mapping[str, Any],
    markdown_coverage_summary: Mapping[str, Any],
    pit_leakage_audit: Mapping[str, Any],
    extraction_provenance_audit: Mapping[str, Any],
    statistical_robustness_audit: Mapping[str, Any],
    gold_review_summary: Mapping[str, Any],
    outcome_labeling_readiness: Mapping[str, Any] | None,
    schema_validation_report: Mapping[str, Any] | None,
) -> str:
    paper = _ensure_mapping(recipe_paper_trading_summary)
    monitor = _ensure_mapping(confidence_impact_monitor)
    markdown = _ensure_mapping(markdown_coverage_summary)
    gold = _ensure_mapping(gold_review_summary)
    readiness = _ensure_mapping(outcome_labeling_readiness)
    audit = _audit_current_record(
        schema_validation_report=schema_validation_report,
        pit_leakage_audit=pit_leakage_audit,
        extraction_provenance_audit=extraction_provenance_audit,
        statistical_robustness_audit=statistical_robustness_audit,
    )
    stock_readiness = _ensure_mapping(readiness.get("stock_price_proxy_readiness"))
    industry_readiness = _ensure_mapping(
        readiness.get("industry_etf_proxy_readiness")
    )
    payload = {
        "forecast_claim_count": len(forecast_rows),
        "outcome_label_count": len(outcome_label_rows),
        "outcome_coverage": _outcome_coverage_counts(outcome_label_rows),
        "paper_trading": {
            "recipe_count": int(paper.get("recipe_count") or 0),
            "paper_trading_run_count": int(paper.get("paper_trading_run_count") or 0),
            "validation_pass_count": int(paper.get("validation_pass_count") or 0),
            "blocked_count": int(paper.get("blocked_count") or 0),
            "status_counts": _count_mapping_values(
                _ensure_mapping(paper.get("status_counts"))
            ),
            "blocker_counts": _count_mapping_values(
                _ensure_mapping(paper.get("blocker_counts"))
            ),
            "mean_cost_adjusted_alpha": paper.get("mean_cost_adjusted_alpha"),
        },
        "confidence_monitor": {
            "observation_count": int(monitor.get("observation_count") or 0),
            "blocked_recipe_count": int(monitor.get("blocked_recipe_count") or 0),
            "unvalidated_confidence_impact_count": int(
                monitor.get("unvalidated_confidence_impact_count") or 0
            ),
            "alpha_decay_fail_count": int(
                monitor.get("alpha_decay_fail_count") or 0
            ),
            "calibration_drift_count": int(
                monitor.get("calibration_drift_count") or 0
            ),
            "blocker_counts": _count_mapping_values(
                _ensure_mapping(monitor.get("blocker_counts"))
            ),
            "drift_status_counts": _count_mapping_values(
                _ensure_mapping(monitor.get("drift_status_counts"))
            ),
            "calibration_drift_rule_counts": _count_mapping_values(
                _ensure_mapping(monitor.get("calibration_drift_rule_counts"))
            ),
        },
        "markdown_coverage": {
            "selected_report_count": int(markdown.get("selected_report_count") or 0),
            "markdown_ready_count": int(markdown.get("markdown_ready_count") or 0),
            "markdown_quality_pass_count": int(
                markdown.get("markdown_quality_pass_count") or 0
            ),
            "llm_extraction_processed_count": int(
                markdown.get("llm_extraction_processed_count") or 0
            ),
            "industry_report_count": int(
                markdown.get("industry_report_count") or 0
            ),
            "stock_report_count": int(markdown.get("stock_report_count") or 0),
            "coverage_gate_status": str(markdown.get("coverage_gate_status") or ""),
            "coverage_gate_blockers": _ensure_list(
                markdown.get("coverage_gate_blockers")
            ),
            "coverage_strata_missing": _ensure_list(
                markdown.get("coverage_strata_missing")
            ),
            "markdown_quality_gap_counts": _count_mapping_values(
                _ensure_mapping(markdown.get("markdown_quality_gap_counts"))
            ),
            "markdown_quality_review_queue_count": int(
                markdown.get("markdown_quality_review_queue_count") or 0
            ),
            "markdown_false_positive_review_queue_count": int(
                markdown.get("markdown_false_positive_review_queue_count") or 0
            ),
            "markdown_quality_spot_check_required": (
                markdown.get("markdown_quality_spot_check_required") is True
            ),
            "report_type_counts": _count_mapping_values(
                _ensure_mapping(markdown.get("report_type_counts"))
            ),
            "sector_bucket_coverage_gaps": _ensure_list(
                markdown.get("sector_bucket_coverage_gaps")
            ),
            "sector_bucket_below_min_count": int(
                markdown.get("sector_bucket_below_min_count") or 0
            ),
            "time_bucket_counts": _count_mapping_values(
                _ensure_mapping(markdown.get("time_bucket_counts"))
            ),
            "institution_bucket_counts": _count_mapping_values(
                _ensure_mapping(markdown.get("institution_bucket_counts"))
            ),
            "report_horizon_bucket_counts": _count_mapping_values(
                _ensure_mapping(markdown.get("report_horizon_bucket_counts"))
            ),
            "evaluability_bucket_counts": _count_mapping_values(
                _ensure_mapping(markdown.get("evaluability_bucket_counts"))
            ),
        },
        "gold_review": {
            "accepted": gold.get("accepted") is True,
            "passed": gold.get("passed") is True,
            "reviewed_claims": int(gold.get("reviewed_claims") or 0),
            "pending_claims": int(gold.get("pending_claims") or 0),
            "total_documents": int(gold.get("total_documents") or 0),
            "metrics": {
                field: _gold_review_metric(gold, _ensure_mapping(gold.get("metrics")), field)
                for field in (
                    *FORECAST_GOLD_REVIEW_MIN_METRICS.keys(),
                    *FORECAST_GOLD_REVIEW_MAX_METRICS.keys(),
                    "stock_target_conflict_reviewed_count",
                )
            },
            "stock_target_conflict_explained": (
                gold.get("stock_target_conflict_explained") is True
                or _ensure_mapping(gold.get("metrics")).get(
                    "stock_target_conflict_explained"
                )
                is True
            ),
        },
        "readiness": {
            "forecast_claim_count": int(readiness.get("forecast_claim_count") or 0),
            "ready_for_outcome_labeling_count": int(
                readiness.get("ready_for_outcome_labeling_count") or 0
            ),
            "proxy_label_ready_count": int(
                readiness.get("proxy_label_ready_count") or 0
            ),
            "blocked_count": int(readiness.get("blocked_count") or 0),
            "mapping_gap_counts": _count_mapping_values(
                _ensure_mapping(readiness.get("mapping_gap_counts"))
            ),
            "stock_price_proxy_readiness": {
                "eligible_claim_count": int(
                    stock_readiness.get("eligible_claim_count") or 0
                ),
                "labelable_forecast_claim_count": int(
                    stock_readiness.get("labelable_forecast_claim_count") or 0
                ),
                "labelable_window_count": int(
                    stock_readiness.get("labelable_window_count") or 0
                ),
                "data_gap_counts": _count_mapping_values(
                    _ensure_mapping(stock_readiness.get("data_gap_counts"))
                ),
            },
            "industry_etf_proxy_readiness": {
                "eligible_claim_count": int(
                    industry_readiness.get("eligible_claim_count") or 0
                ),
                "labelable_forecast_claim_count": int(
                    industry_readiness.get("labelable_forecast_claim_count") or 0
                ),
                "labelable_window_count": int(
                    industry_readiness.get("labelable_window_count") or 0
                ),
                "data_gap_counts": _count_mapping_values(
                    _ensure_mapping(industry_readiness.get("data_gap_counts"))
                ),
            },
        },
        "audits": audit,
    }
    encoded = json.dumps(
        _jsonable(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def _monitor_refresh_record_passed(row: Mapping[str, Any]) -> bool:
    calibration_rule_counts = _count_mapping_values(
        _ensure_mapping(row.get("calibration_drift_rule_counts"))
    )
    aggregate_calibration_drift_count = int(
        row.get("aggregate_calibration_drift_count") or 0
    )
    # Per-recipe paper-trading blockers and alpha-decay failures freeze the
    # affected recipes through confidence_impact_monitor queues. They should not
    # block the whole evolution pool when no positive confidence impact was
    # granted and no aggregate calibration drift is present.
    computed_passed = (
        int(row.get("unvalidated_confidence_impact_count") or 0) == 0
        and aggregate_calibration_drift_count == 0
        and not calibration_rule_counts
    )
    if "accepted" in row and row.get("accepted") is not True:
        return False
    return computed_passed


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
    seen_vintages: set[str] = set()
    count = 0
    for row in reversed(list(rows)):
        vintage_key = _history_vintage_key(row)
        if vintage_key in seen_vintages:
            continue
        seen_vintages.add(vintage_key)
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


def _evolution_gap_distribution_counts(
    outcome_labeling_readiness: Mapping[str, Any],
) -> dict[str, int]:
    readiness = _ensure_mapping(outcome_labeling_readiness)
    unlabelable = _count_mapping_values(
        _ensure_mapping(readiness.get("unlabelable_mapping_gap_counts"))
    )
    if unlabelable:
        return unlabelable
    return _count_mapping_values(_ensure_mapping(readiness.get("mapping_gap_counts")))


def _trailing_gap_distribution_stable_count(
    rows: Sequence[Mapping[str, Any]],
) -> int:
    seen_vintages: set[str] = set()
    count = 0
    for row in reversed(list(rows)):
        vintage_key = _history_vintage_key(row)
        if vintage_key in seen_vintages:
            continue
        seen_vintages.add(vintage_key)
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
    data_vintage_hash = str(record.get("data_vintage_hash") or "").strip()
    deduped = [
        dict(row)
        for row in rows
        if (
            (
                _valid_data_vintage_hash(row.get("data_vintage_hash"))
                and str(row.get("data_vintage_hash") or "").strip()
                != data_vintage_hash
            )
            if _valid_data_vintage_hash(data_vintage_hash)
            else str(row.get("run_id") or "") != run_id
        )
    ]
    deduped.append(dict(record))
    return deduped[-EVOLUTION_REFRESH_HISTORY_MAX_ROWS:]


PUBLIC_ARTIFACT_PRIVATE_TEXT_KEYS = {
    "abstract",
    "claim_text",
    "manual_claim_text",
    "markdown_path",
    "original_markdown",
    "pdf_path",
    "pdf_url",
    "retrieval_locator",
    "source_span_ids",
    "source_span_text",
    "source_text",
    "title",
    "url",
}


def _public_payload_private_text_included(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = str(key).strip().lower()
            if normalized_key == "private_text_included":
                continue
            if normalized_key in PUBLIC_ARTIFACT_PRIVATE_TEXT_KEYS and bool(item):
                return True
            if _public_payload_private_text_included(item):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(value, str):
        return any(_public_payload_private_text_included(item) for item in value)
    return False


def _monitor_refresh_history_record(
    *,
    run_id: str,
    data_vintage_hash: str,
    confidence_impact_monitor: Mapping[str, Any],
) -> dict[str, Any]:
    monitor = _ensure_mapping(confidence_impact_monitor)
    record = {
        "history_id": _stable_id(
            "MONHIST",
            {"data_vintage_hash": data_vintage_hash or run_id},
        ),
        "history_type": "confidence_impact_monitor",
        "run_id": run_id,
        "data_vintage_hash": data_vintage_hash,
        "as_of_datetime": _utc_now(),
        "accepted": _monitor_refresh_record_passed(monitor),
        "observation_count": int(monitor.get("observation_count") or 0),
        "blocked_recipe_count": int(monitor.get("blocked_recipe_count") or 0),
        "unvalidated_confidence_impact_count": int(
            monitor.get("unvalidated_confidence_impact_count") or 0
        ),
        "alpha_decay_fail_count": int(monitor.get("alpha_decay_fail_count") or 0),
        "calibration_drift_count": int(monitor.get("calibration_drift_count") or 0),
        "aggregate_calibration_drift_count": int(
            monitor.get("aggregate_calibration_drift_count") or 0
        ),
        "calibration_drift_rule_counts": _count_mapping_values(
            _ensure_mapping(monitor.get("calibration_drift_rule_counts"))
        ),
        "blocker_counts": _count_mapping_values(
            _ensure_mapping(monitor.get("blocker_counts"))
        ),
    }
    record["private_text_included"] = _public_payload_private_text_included(record)
    return record


def _audit_refresh_history_record(
    *,
    run_id: str,
    data_vintage_hash: str,
    audit_record: Mapping[str, Any],
) -> dict[str, Any]:
    audit = _ensure_mapping(audit_record)
    record = {
        "history_id": _stable_id(
            "AUDHIST",
            {"data_vintage_hash": data_vintage_hash or run_id},
        ),
        "history_type": "schema_pit_provenance_statistical_audit",
        "run_id": run_id,
        "data_vintage_hash": data_vintage_hash,
        "as_of_datetime": _utc_now(),
        "accepted": _audit_refresh_record_passed(audit),
        "schema_accepted": audit.get("schema_accepted") is True,
        "pit_accepted": audit.get("pit_accepted") is True,
        "provenance_accepted": audit.get("provenance_accepted") is True,
        "statistical_accepted": audit.get("statistical_accepted") is True,
    }
    record["private_text_included"] = _public_payload_private_text_included(record)
    return record


def _gap_distribution_history_record(
    *,
    run_id: str,
    data_vintage_hash: str,
    outcome_labeling_readiness: Mapping[str, Any],
) -> dict[str, Any]:
    readiness = _ensure_mapping(outcome_labeling_readiness)
    gap_counts = _evolution_gap_distribution_counts(readiness)
    all_mapping_gap_counts = _count_mapping_values(
        _ensure_mapping(readiness.get("mapping_gap_counts"))
    )
    total_gap_count = sum(gap_counts.values())
    max_gap_name = ""
    max_gap_share = 0.0
    if total_gap_count:
        max_gap_name, max_gap_count = max(gap_counts.items(), key=lambda item: item[1])
        max_gap_share = max_gap_count / total_gap_count
    stable = total_gap_count == 0 or max_gap_share <= 0.80
    record = {
        "history_id": _stable_id(
            "GAPHIST",
            {"data_vintage_hash": data_vintage_hash or run_id},
        ),
        "history_type": "mapping_gap_distribution",
        "run_id": run_id,
        "data_vintage_hash": data_vintage_hash,
        "as_of_datetime": _utc_now(),
        "accepted": stable,
        "stable": stable,
        "gap_counts": gap_counts,
        "all_mapping_gap_counts": all_mapping_gap_counts,
        "gap_count_basis": (
            "unlabelable_mapping_gap_counts"
            if _count_mapping_values(
                _ensure_mapping(readiness.get("unlabelable_mapping_gap_counts"))
            )
            else "mapping_gap_counts"
        ),
        "total_gap_count": total_gap_count,
        "max_gap_name": max_gap_name,
        "max_gap_share": round(max_gap_share, 6),
    }
    record["private_text_included"] = _public_payload_private_text_included(record)
    return record


def _normalize_monitor_refresh_history_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        comparable = dict(item)
        comparable.pop("accepted", None)
        item["accepted"] = _monitor_refresh_record_passed(comparable)
        normalized.append(item)
    return normalized


def _prepare_evolution_refresh_history(
    *,
    registry_dir: Path,
    run_id: str,
    forecast_rows: Sequence[Mapping[str, Any]],
    outcome_label_rows: Sequence[Mapping[str, Any]],
    recipe_paper_trading_summary: Mapping[str, Any],
    confidence_impact_monitor: Mapping[str, Any],
    markdown_coverage_summary: Mapping[str, Any],
    schema_validation_report: Mapping[str, Any],
    pit_leakage_audit: Mapping[str, Any],
    extraction_provenance_audit: Mapping[str, Any],
    statistical_robustness_audit: Mapping[str, Any],
    gold_review_summary: Mapping[str, Any],
    outcome_labeling_readiness: Mapping[str, Any],
) -> dict[str, list[Mapping[str, Any]]]:
    monitor_history_rows = _normalize_monitor_refresh_history_rows(
        _read_evolution_history_rows(registry_dir / "monitor_refresh_history.jsonl")
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
    data_vintage_hash = _evolution_data_vintage_hash(
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
    )
    return {
        "monitor_previous": monitor_history_rows,
        "audit_previous": audit_history_rows,
        "gap_previous": gap_distribution_history_rows,
        "monitor_updated": _append_evolution_history_record(
            monitor_history_rows,
            _monitor_refresh_history_record(
                run_id=run_id,
                data_vintage_hash=data_vintage_hash,
                confidence_impact_monitor=confidence_impact_monitor,
            ),
        ),
        "audit_updated": _append_evolution_history_record(
            audit_history_rows,
            _audit_refresh_history_record(
                run_id=run_id,
                data_vintage_hash=data_vintage_hash,
                audit_record=audit_record,
            ),
        ),
        "gap_updated": _append_evolution_history_record(
            gap_distribution_history_rows,
            _gap_distribution_history_record(
                run_id=run_id,
                data_vintage_hash=data_vintage_hash,
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


def _audit_history_dependency(
    *,
    current_audit_record: Mapping[str, Any],
    trailing_audit_pass_count: int,
) -> dict[str, Any]:
    audit_fields = (
        "schema_accepted",
        "pit_accepted",
        "provenance_accepted",
        "statistical_accepted",
    )
    blocking_components = [
        field.removesuffix("_accepted")
        for field in audit_fields
        if current_audit_record.get(field) is not True
    ]
    if blocking_components:
        status = "current_gate_blocked"
        next_action = (
            "clear_current_schema_pit_provenance_statistical_blockers_before_"
            "counting_audit_refresh_history"
        )
    elif trailing_audit_pass_count < EVOLUTION_GATE_MIN_CONSECUTIVE_AUDIT_REFRESHES:
        status = "history_below_threshold"
        next_action = "run_distinct_derived_refreshes_after_current_audits_pass"
    else:
        status = "ready"
        next_action = "none"
    return {
        "status": status,
        "blocking_components": blocking_components,
        "trailing_audit_pass_count": trailing_audit_pass_count,
        "min_consecutive_audit_refreshes": (
            EVOLUTION_GATE_MIN_CONSECUTIVE_AUDIT_REFRESHES
        ),
        "history_counts_only_passing_current_audits": True,
        "refresh_without_current_audit_pass_can_satisfy_history": False,
        "next_action": next_action,
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
    data_vintage_hash = _evolution_data_vintage_hash(
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
    )
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
    after_cost_summary = _ensure_mapping(
        paper_summary.get("after_cost_paper_trading_summary")
    )
    if not str(after_cost_summary.get("status") or "").strip():
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
                "after_cost_paper_trading_summary": after_cost_summary,
            },
            blockers=paper_blockers,
        )
    )

    monitor = _ensure_mapping(confidence_impact_monitor)
    current_monitor_record = _monitor_refresh_history_record(
        run_id=run_id,
        data_vintage_hash=data_vintage_hash,
        confidence_impact_monitor=monitor,
    )
    monitor_records = [
        *[dict(row) for row in monitor_refresh_history_rows],
        current_monitor_record,
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
                "Confidence impact monitor must have no unvalidated positive "
                "confidence impact or aggregate calibration drift for three "
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
                "calibration_drift_count": int(
                    monitor.get("calibration_drift_count") or 0
                ),
                "aggregate_calibration_drift_count": int(
                    monitor.get("aggregate_calibration_drift_count") or 0
                ),
                "calibration_drift_rule_counts": _count_mapping_values(
                    _ensure_mapping(monitor.get("calibration_drift_rule_counts"))
                ),
                "trailing_monitor_pass_count": monitor_trailing_pass_count,
                "trailing_monitor_distinct_vintage_count": monitor_trailing_pass_count,
                "data_vintage_hash": data_vintage_hash,
                "distinct_data_vintage_required": True,
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
    current_audit_history_record = _audit_refresh_history_record(
        run_id=run_id,
        data_vintage_hash=data_vintage_hash,
        audit_record=current_audit_record,
    )
    audit_records = [
        *[dict(row) for row in audit_refresh_history_rows],
        current_audit_history_record,
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
                "trailing_audit_distinct_vintage_count": audit_trailing_pass_count,
                "data_vintage_hash": data_vintage_hash,
                "distinct_data_vintage_required": True,
                "audit_history_dependency": _audit_history_dependency(
                    current_audit_record=current_audit_record,
                    trailing_audit_pass_count=audit_trailing_pass_count,
                ),
            },
            blockers=audit_blockers,
        )
    )

    gold_passed, gold_evidence, gold_blockers = _forecast_gold_review_gate(
        gold_review_summary=gold_review_summary,
        outcome_labeling_readiness=outcome_labeling_readiness,
    )
    checks.append(
        _evolution_gate_check(
            check_id="RI-EVOL-05",
            requirement=(
                "Manual forecast gold-set review must pass before prompt "
                "evolution uses extracted target, direction, or horizon signals."
            ),
            passed=gold_passed,
            evidence=gold_evidence,
            blockers=gold_blockers,
        )
    )

    readiness = _ensure_mapping(outcome_labeling_readiness)
    current_gap_counts = _evolution_gap_distribution_counts(readiness)
    all_mapping_gap_counts = _count_mapping_values(
        _ensure_mapping(readiness.get("mapping_gap_counts"))
    )
    current_gap_record = _gap_distribution_history_record(
        run_id=run_id,
        data_vintage_hash=data_vintage_hash,
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
                "trailing_gap_distribution_distinct_vintage_count": (
                    gap_trailing_stable_count
                ),
                "data_vintage_hash": data_vintage_hash,
                "distinct_data_vintage_required": True,
                "current_mapping_gap_counts": current_gap_counts,
                "current_all_mapping_gap_counts": all_mapping_gap_counts,
                "gap_count_basis": (
                    "unlabelable_mapping_gap_counts"
                    if _count_mapping_values(
                        _ensure_mapping(
                            readiness.get("unlabelable_mapping_gap_counts")
                        )
                    )
                    else "mapping_gap_counts"
                ),
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
    markdown_quality_review_queue_count = int(
        markdown.get("markdown_quality_review_queue_count") or 0
    )
    markdown_false_positive_review_queue_count = int(
        markdown.get("markdown_false_positive_review_queue_count") or 0
    )
    markdown_quality_spot_check_required = (
        markdown.get("markdown_quality_spot_check_required") is True
    )
    markdown_blockers = list(coverage_blockers)
    if str(markdown.get("coverage_gate_status") or "") != "passed":
        markdown_blockers = markdown_blockers or ["markdown_coverage_gate_not_passed"]
    if markdown_quality_review_queue_count:
        markdown_blockers.append("markdown_quality_review_queue_pending")
    if markdown_false_positive_review_queue_count:
        markdown_blockers.append("markdown_false_positive_review_queue_pending")
    if markdown_quality_spot_check_required:
        markdown_blockers.append("markdown_quality_spot_check_required")
    coverage_passed = not markdown_blockers
    checks.append(
        _evolution_gate_check(
            check_id="RI-EVOL-07",
            requirement=(
                "Markdown coverage must pass P9 corpus thresholds before "
                "evolution depends on report-derived Markdown evidence."
            ),
            passed=coverage_passed,
            evidence={
                "coverage_gate_status": str(markdown.get("coverage_gate_status") or ""),
                "coverage_gate_blockers": coverage_blockers,
                "coverage_targets": _ensure_mapping(markdown.get("coverage_targets")),
                "coverage_shortfalls": _ensure_mapping(
                    markdown.get("coverage_shortfalls")
                ),
                "coverage_strata_targets": _ensure_mapping(
                    markdown.get("coverage_strata_targets")
                ),
                "coverage_strata_missing": _ensure_list(
                    markdown.get("coverage_strata_missing")
                ),
                "selected_report_count": int(
                    markdown.get("selected_report_count") or 0
                ),
                "markdown_ready_count": int(
                    markdown.get("markdown_ready_count") or 0
                ),
                "markdown_quality_pass_count": int(
                    markdown.get("markdown_quality_pass_count") or 0
                ),
                "llm_extraction_processed_count": int(
                    markdown.get("llm_extraction_processed_count") or 0
                ),
                "industry_report_count": int(
                    markdown.get("industry_report_count") or 0
                ),
                "stock_report_count": int(markdown.get("stock_report_count") or 0),
                "stock_outcome_120d_ready_report_count": int(
                    markdown.get("stock_outcome_120d_ready_report_count") or 0
                ),
                "stock_outcome_age_bucket_counts": _count_mapping_values(
                    _ensure_mapping(markdown.get("stock_outcome_age_bucket_counts"))
                ),
                "sector_bucket_coverage_gaps": _ensure_list(
                    markdown.get("sector_bucket_coverage_gaps")
                ),
                "sector_bucket_below_min_count": int(
                    markdown.get("sector_bucket_below_min_count") or 0
                ),
                "time_bucket_counts": _count_mapping_values(
                    _ensure_mapping(markdown.get("time_bucket_counts"))
                ),
                "institution_bucket_counts": _count_mapping_values(
                    _ensure_mapping(markdown.get("institution_bucket_counts"))
                ),
                "report_horizon_bucket_counts": _count_mapping_values(
                    _ensure_mapping(markdown.get("report_horizon_bucket_counts"))
                ),
                "evaluability_bucket_counts": _count_mapping_values(
                    _ensure_mapping(markdown.get("evaluability_bucket_counts"))
                ),
                "markdown_quality_review_queue_count": (
                    markdown_quality_review_queue_count
                ),
                "markdown_false_positive_review_queue_count": (
                    markdown_false_positive_review_queue_count
                ),
                "markdown_quality_spot_check_required": (
                    markdown_quality_spot_check_required
                ),
            },
            blockers=[] if coverage_passed else markdown_blockers,
        )
    )

    blockers = [
        blocker
        for check in checks
        for blocker in _ensure_list(check.get("blockers"))
    ]
    gate = {
        "gate_id": "RKE-REPORT-INTELLIGENCE-EVOLUTION-READINESS-GATE",
        "run_id": run_id,
        "data_vintage_hash": data_vintage_hash,
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
        "requirement_shortfalls": _evolution_gate_requirement_shortfalls(checks),
        "blockers": sorted(set(blockers)),
        "blocker_count": len(set(blockers)),
        "policy": (
            "Prompt and agent evolution remains blocked until governed aggregate "
            "PIT outcome coverage, paper-trading, monitor stability, audit history, "
            "gold-set quality, gap stability, and Markdown coverage gates pass; this "
            "artifact stores aggregate evidence only and cannot change production prompts."
        ),
    }
    gate["private_text_included"] = _public_payload_private_text_included(gate)
    return gate


def _evolution_gate_public_outcome_label_rows(
    *,
    outcome_labeling_readiness: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    readiness = _ensure_mapping(outcome_labeling_readiness)
    rows: list[Mapping[str, Any]] = []
    channel_specs = (
        (
            "stock_price_proxy_readiness",
            "stock_price_proxy",
            "pit_stock_price_window",
            "stock",
        ),
        (
            "industry_etf_proxy_readiness",
            "industry_etf_proxy",
            "pit_industry_etf_price_window",
            "industry",
        ),
    )
    for readiness_key, label_type, label_source, synthetic_prefix in channel_specs:
        channel = _ensure_mapping(readiness.get(readiness_key))
        claim_ids = [
            str(item).strip()
            for item in _ensure_list(channel.get("labelable_forecast_claim_ids"))
            if str(item).strip()
        ]
        target_count = int(channel.get("labelable_forecast_claim_count") or len(claim_ids))
        if target_count <= 0:
            continue
        while len(claim_ids) < target_count:
            claim_ids.append(
                f"COUNT-ONLY-{synthetic_prefix}-outcome-{len(claim_ids) + 1:06d}"
            )
        for claim_id in claim_ids[:target_count]:
            rows.append(
                {
                    "forecast_claim_id": claim_id,
                    "label_type": label_type,
                    "outcome_label_source": label_source,
                    "public_count_only_fallback": True,
                }
            )
    return rows


def write_report_intelligence_evolution_readiness_gate(
    registry_dir: str | Path,
    *,
    run_id: str = "RIR-PUBLIC-EVOLUTION-GATE",
) -> dict[str, Any]:
    """Rebuild only the public evolution gate from existing registry artifacts."""
    registry_path = Path(registry_dir)
    root_path = registry_path.parent.parent
    blockers: list[str] = []
    gate_path = registry_path / "evolution_readiness_gate.json"
    forecast_rows = _read_registry_jsonl(
        registry_path / "report_forecast_ledger.jsonl",
        label="report_forecast_ledger",
        blockers=blockers,
    )
    outcome_labeling_readiness = _read_registry_json(
        registry_path / "outcome_labeling_readiness.json",
        label="outcome_labeling_readiness",
        blockers=blockers,
    )
    outcome_label_path = registry_path / "report_outcome_labels.jsonl"
    outcome_label_missing = not _jsonl_has_mapping_rows(outcome_label_path)
    public_outcome_fallback_rows = (
        _evolution_gate_public_outcome_label_rows(
            outcome_labeling_readiness=outcome_labeling_readiness,
        )
        if outcome_label_missing
        else []
    )
    if outcome_label_missing and not public_outcome_fallback_rows and gate_path.exists():
        existing_gate_blockers: list[str] = []
        existing_gate = _read_registry_json(
            gate_path,
            label="evolution_readiness_gate",
            blockers=existing_gate_blockers,
        )
        if existing_gate:
            blockers.append("report_outcome_labels: missing_or_empty_private_input")
            blockers.extend(existing_gate_blockers)
            return {
                "evolution_readiness_gate": str(gate_path),
                "gate_status": str(existing_gate.get("gate_status") or ""),
                "blocker_count": int(existing_gate.get("blocker_count") or 0),
                "input_load_blockers": blockers,
                "preserved_existing_gate": True,
            }
    outcome_label_rows = (
        _read_registry_jsonl(
            outcome_label_path,
            label="report_outcome_labels",
            blockers=blockers,
        )
        if not outcome_label_missing
        else public_outcome_fallback_rows
    )
    public_fallbacks: list[str] = []
    if outcome_label_missing and public_outcome_fallback_rows:
        public_fallbacks.append("report_outcome_labels")
    recipe_paper_trading_summary = _read_registry_json(
        registry_path / "recipe_paper_trading_summary.json",
        label="recipe_paper_trading_summary",
        blockers=blockers,
    )
    confidence_impact_monitor = _read_registry_json(
        registry_path / "confidence_impact_monitor.json",
        label="confidence_impact_monitor",
        blockers=blockers,
    )
    recipe_paper_trading_summary = _read_registry_json(
        registry_path / "recipe_paper_trading_summary.json",
        label="recipe_paper_trading_summary",
        blockers=blockers,
    )
    markdown_coverage_summary = _read_registry_json(
        registry_path / "markdown_coverage_summary.json",
        label="markdown_coverage_summary",
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
    gold_review_summary = _read_registry_json(
        registry_path.parent / "gold_sets/tushare_research_reports.review_summary.json",
        label="gold_review_summary",
        blockers=blockers,
    )
    monitor_refresh_history_rows = _read_registry_jsonl(
        registry_path / "monitor_refresh_history.jsonl",
        label="monitor_refresh_history",
        blockers=blockers,
    )
    audit_refresh_history_rows = _read_registry_jsonl(
        registry_path / "audit_refresh_history.jsonl",
        label="audit_refresh_history",
        blockers=blockers,
    )
    gap_distribution_history_rows = _read_registry_jsonl(
        registry_path / "gap_distribution_history.jsonl",
        label="gap_distribution_history",
        blockers=blockers,
    )
    gate = build_report_intelligence_evolution_readiness_gate(
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
        schema_validation_report=_read_schema_validation_report(root_path),
        monitor_refresh_history_rows=monitor_refresh_history_rows,
        audit_refresh_history_rows=audit_refresh_history_rows,
        gap_distribution_history_rows=gap_distribution_history_rows,
    )
    if public_fallbacks:
        gate = dict(gate)
        gate["count_only_public_fallbacks"] = sorted(public_fallbacks)
        gate["private_input_fallback_policy"] = (
            "When private outcome-label JSONL is absent, the public evolution "
            "gate uses labelable forecast-claim ids/counts from "
            "outcome_labeling_readiness.json; fallback rows contain no report "
            "prose, titles, abstracts, URLs, source spans, reviewer text, or "
            "price-window returns."
        )
        gate["private_text_included"] = _public_payload_private_text_included(gate)
    if blockers:
        gate = dict(gate)
        gate["input_load_blockers"] = blockers
        gate["blockers"] = sorted(
            set([*_ensure_list(gate.get("blockers")), "evolution_input_load_gap"])
        )
        gate["blocker_count"] = len(gate["blockers"])
        gate["gate_status"] = "blocked"
        gate["promotion_state"] = "blocked_before_prompt_evolution"
        gate["private_text_included"] = _public_payload_private_text_included(gate)
    written = _write_json(gate_path, gate)
    return {
        "evolution_readiness_gate": str(written["path"]),
        "gate_status": str(gate.get("gate_status") or ""),
        "blocker_count": int(gate.get("blocker_count") or 0),
        "input_load_blockers": blockers,
        "count_only_public_fallbacks": sorted(public_fallbacks),
        "preserved_existing_gate": False,
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


def _integer_mapping_values(mapping: Mapping[str, Any]) -> dict[str, int]:
    values: dict[str, int] = {}
    for key, value in mapping.items():
        key_text = str(key).strip()
        if not key_text:
            continue
        try:
            values[key_text] = int(value)
        except (TypeError, ValueError):
            continue
    return dict(sorted(values.items()))


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
    candidate = {
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
        "policy": (
            "Prompt mutation candidates are derived from governed aggregate "
            "evidence only; they do not modify production prompts and cannot "
            "include private source content, retrieval locators, or private "
            "prompt content."
        ),
    }
    candidate["private_text_included"] = _public_payload_private_text_included(candidate)
    candidates.append(candidate)


def _paper_trading_blocker_counts(
    recipe_paper_trading_runs: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for run in recipe_paper_trading_runs:
        for reason in _ensure_list(run.get("blocked_reasons")):
            _increment_count(counts, reason)
    return counts


def _paper_trading_summary_diagnostic_evidence(
    recipe_paper_trading_summary: Mapping[str, Any] | None,
) -> dict[str, Any]:
    summary = _ensure_mapping(recipe_paper_trading_summary)
    diagnostics = _ensure_mapping(summary.get("direct_pit_binding_diagnostics"))
    if not diagnostics:
        return {}
    evidence: dict[str, Any] = {
        "artifact_path": "registry/report_intelligence/recipe_paper_trading_summary.json",
        "field": "direct_pit_binding_diagnostics",
        "status": str(diagnostics.get("status") or ""),
        "recipe_count": int(diagnostics.get("recipe_count") or 0),
        "direct_pit_bound_recipe_count": int(
            diagnostics.get("direct_pit_bound_recipe_count") or 0
        ),
        "no_direct_recipe_outcome_binding_count": int(
            diagnostics.get("no_direct_recipe_outcome_binding_count") or 0
        ),
        "insufficient_effective_n_count": int(
            diagnostics.get("insufficient_effective_n_count") or 0
        ),
        "required_tools_not_shadow_implemented_count": int(
            diagnostics.get("required_tools_not_shadow_implemented_count") or 0
        ),
        "next_actions": [
            str(action)
            for action in _ensure_list(diagnostics.get("next_actions"))
            if str(action).strip()
        ],
    }
    details = _ensure_mapping(diagnostics.get("binding_gap_details"))
    if details:
        evidence["binding_gap_details"] = {
            "diagnostic_version": str(details.get("diagnostic_version") or ""),
            "artifact_counts": _integer_mapping_values(
                _ensure_mapping(details.get("artifact_counts"))
            ),
            "method_source_linkage": _integer_mapping_values(
                _ensure_mapping(details.get("method_source_linkage"))
            ),
            "forecast_outcome_linkage": _integer_mapping_values(
                _ensure_mapping(details.get("forecast_outcome_linkage"))
            ),
            "footprint_source_linkage": _integer_mapping_values(
                _ensure_mapping(details.get("footprint_source_linkage"))
            ),
            "recipe_binding_linkage": _integer_mapping_values(
                _ensure_mapping(details.get("recipe_binding_linkage"))
            ),
            "missing_artifact_flags": [
                str(flag)
                for flag in _ensure_list(details.get("missing_artifact_flags"))
                if str(flag).strip()
            ],
            "next_actions": [
                str(action)
                for action in _ensure_list(details.get("next_actions"))
                if str(action).strip()
            ],
        }
    return evidence


def _paper_trading_summary_diagnostic_blockers(
    recipe_paper_trading_summary: Mapping[str, Any] | None,
) -> list[str]:
    diagnostics = _ensure_mapping(
        _ensure_mapping(recipe_paper_trading_summary).get(
            "direct_pit_binding_diagnostics"
        )
    )
    blockers: list[str] = []
    if str(diagnostics.get("status") or "") == "blocked_no_direct_pit_binding":
        blockers.append("direct_pit_outcome_binding_required")
    if int(diagnostics.get("insufficient_effective_n_count") or 0):
        blockers.append("effective_sample_expansion_required")
    if int(diagnostics.get("required_tools_not_shadow_implemented_count") or 0):
        blockers.append("requested_shadow_tools_required")
    details = _ensure_mapping(diagnostics.get("binding_gap_details"))
    missing_flags = {
        str(flag)
        for flag in _ensure_list(details.get("missing_artifact_flags"))
        if str(flag).strip()
    }
    if "forecast_claims_absent" in missing_flags:
        blockers.append("private_forecast_claims_required")
    if "outcome_labels_absent" in missing_flags:
        blockers.append("private_outcome_labels_required")
    if "analytical_footprints_absent" in missing_flags:
        blockers.append("private_analytical_footprints_required")
    if "method_source_footprints_empty" in missing_flags:
        blockers.append("method_source_footprint_links_required")
    return list(dict.fromkeys(blockers))


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
    recipe_paper_trading_summary: Mapping[str, Any] | None = None,
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
    regime_gap_counts = _count_mapping_values(
        _ensure_mapping(readiness.get("regime_gap_counts"))
    )
    mechanism_gap_counts = _count_mapping_values(
        _ensure_mapping(readiness.get("mechanism_gap_counts"))
    )
    macro_regime_counts = _count_mapping_values(
        _ensure_mapping(readiness.get("macro_regime_counts"))
    )
    source_text_macro_regime_counts = _count_mapping_values(
        _ensure_mapping(readiness.get("source_text_macro_regime_counts"))
    )
    as_of_date_macro_regime_counts = _count_mapping_values(
        _ensure_mapping(readiness.get("as_of_date_macro_regime_counts"))
    )
    macro_regime_source_counts = _count_mapping_values(
        _ensure_mapping(readiness.get("macro_regime_source_counts"))
    )
    industry_cycle_regime_counts = _count_mapping_values(
        _ensure_mapping(readiness.get("industry_cycle_regime_counts"))
    )
    outcome_counts = _outcome_coverage_counts(outcome_label_rows)
    outcome_gate_check = _evolution_gate_check_by_id(evolution_gate, "RI-EVOL-01")
    outcome_gate_evidence = _ensure_mapping(outcome_gate_check.get("evidence"))
    if not outcome_label_rows and outcome_gate_evidence:
        for key in (
            "unique_outcome_claim_count",
            "stock_proxy_unique_claim_count",
            "industry_proxy_unique_claim_count",
        ):
            try:
                outcome_counts[key] = int(outcome_gate_evidence.get(key) or 0)
            except (TypeError, ValueError):
                pass
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
                    "forecast_claim_count": int(
                        outcome_gate_evidence.get("forecast_claim_count")
                        or len(forecast_rows)
                    ),
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
    fallback_gold_passed, fallback_gold_evidence, fallback_gold_blockers = (
        _forecast_gold_review_gate(
            gold_review_summary=gold,
            outcome_labeling_readiness=outcome_labeling_readiness,
        )
    )
    gold_passed = gold_check.get("passed") is True if gold_check else fallback_gold_passed
    if gold_check_blockers or (gold and not gold_passed):
        gold_evidence_source = (
            gold_check_evidence if gold_check else fallback_gold_evidence
        )
        gold_evidence_blockers = gold_check_blockers or fallback_gold_blockers
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
                    "total_documents": int(
                        gold_evidence_source.get("total_documents") or 0
                    ),
                    "pending_claims": int(
                        gold_evidence_source.get("pending_claims") or 0
                    ),
                    "metrics": _ensure_mapping(gold_evidence_source.get("metrics")),
                    "thresholds": _ensure_mapping(
                        gold_evidence_source.get("thresholds")
                    ),
                    "stock_target_conflict_count": int(
                        gold_evidence_source.get("stock_target_conflict_count") or 0
                    ),
                    "stock_target_conflict_reviewed_count": int(
                        gold_evidence_source.get(
                            "stock_target_conflict_reviewed_count"
                        )
                        or 0
                    ),
                    "stock_target_conflict_explained": (
                        gold_evidence_source.get("stock_target_conflict_explained")
                        is True
                    ),
                    "blockers": gold_evidence_blockers,
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
                "Accumulate three consecutive clean derived refreshes across "
                "distinct aggregate data vintages with "
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
                "three_distinct_clean_data_vintages_required",
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
    regime_mechanism_gap_count = sum(regime_gap_counts.values()) + sum(
        mechanism_gap_counts.values()
    )
    hard_regime_mechanism_gaps = {
        "regime_context_missing",
        "regime_context_unclassified",
        "economic_mechanism_missing",
        "mechanism_evaluable_impact_missing",
        "possible_operational_only_mechanism",
    }
    hard_gap_count = sum(
        count
        for key, count in {
            **regime_gap_counts,
            **mechanism_gap_counts,
        }.items()
        if key in hard_regime_mechanism_gaps
    )
    if regime_mechanism_gap_count:
        _add_prompt_mutation_candidate(
            candidates,
            run_id=run_id,
            candidate_type="regime_mechanism_extraction_rule",
            target_scope="report_intelligence.forecast_claim_structure",
            target_component="forecast_extraction_prompt",
            proposed_change=(
                "Tighten forecast claim extraction so macro regime, industry "
                "cycle regime, company capability, economic mechanism, and "
                "evaluable impact are separated before a claim can inform prompt "
                "evolution."
            ),
            trigger_sources=[
                "outcome_labeling_readiness",
                "forecast_claims",
            ],
            evidence_refs=[
                {
                    "artifact_path": "registry/report_intelligence/outcome_labeling_readiness.json",
                    "field": "regime_gap_counts.mechanism_gap_counts",
                    "regime_gap_counts": regime_gap_counts,
                    "mechanism_gap_counts": mechanism_gap_counts,
                    "macro_regime_counts": macro_regime_counts,
                    "source_text_macro_regime_counts": (
                        source_text_macro_regime_counts
                    ),
                    "as_of_date_macro_regime_counts": (
                        as_of_date_macro_regime_counts
                    ),
                    "macro_regime_source_counts": macro_regime_source_counts,
                    "industry_cycle_regime_counts": industry_cycle_regime_counts,
                    "regime_gap_forecast_claim_count": len(
                        {
                            str(item)
                            for item in _ensure_list(
                                readiness.get("regime_gap_forecast_claim_ids")
                            )
                            if str(item).strip()
                        }
                    ),
                    "mechanism_gap_forecast_claim_count": len(
                        {
                            str(item)
                            for item in _ensure_list(
                                readiness.get("mechanism_gap_forecast_claim_ids")
                            )
                            if str(item).strip()
                        }
                    ),
                    "hard_gap_count": hard_gap_count,
                    "diagnostic_gap_policy": (
                        "company_capability_only_no_regime_context is diagnostic; "
                        "missing or unclassified regime and missing mechanism are "
                        "prompt-evolution blockers"
                    ),
                }
            ],
            severity="high" if hard_gap_count else "medium",
            blocked_by=[
                "manual_gold_set_regime_mechanism_review_required",
                "paper_trading_validation_required",
            ],
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
    paper_diagnostic_evidence = _paper_trading_summary_diagnostic_evidence(
        recipe_paper_trading_summary
    )
    paper_diagnostic_blockers = _paper_trading_summary_diagnostic_blockers(
        recipe_paper_trading_summary
    )
    paper_blocker_counts = _paper_trading_blocker_counts(recipe_paper_trading_runs)
    if paper_blocker_counts:
        evidence_refs = [
            {
                "artifact_path": "registry/report_intelligence/recipe_paper_trading_runs.jsonl",
                "field": "blocked_reasons",
                "blocker_counts": dict(sorted(paper_blocker_counts.items())),
            }
        ]
        if paper_diagnostic_evidence:
            evidence_refs.append(paper_diagnostic_evidence)
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
                "recipe_paper_trading_summary",
            ],
            evidence_refs=evidence_refs,
            severity="high"
            if paper_blocker_counts.get("required_tools_not_shadow_implemented", 0)
            else "medium",
            blocked_by=[
                "paper_trading_validation_required",
                *paper_diagnostic_blockers,
            ],
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
        evidence_refs = [
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
        ]
        if paper_diagnostic_evidence:
            evidence_refs.append(paper_diagnostic_evidence)
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
            evidence_refs=evidence_refs,
            severity="high",
            blocked_by=[
                "paper_trading_validation_required",
                *paper_diagnostic_blockers,
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
    markdown_quality_review_queue_count = int(
        markdown_summary.get("markdown_quality_review_queue_count") or 0
    )
    markdown_false_positive_review_queue_count = int(
        markdown_summary.get("markdown_false_positive_review_queue_count") or 0
    )
    markdown_quality_spot_check_required = (
        markdown_summary.get("markdown_quality_spot_check_required") is True
    )
    if (
        str(markdown_summary.get("coverage_gate_status") or "") == "blocked"
        or coverage_gate_blockers
        or markdown_quality_review_queue_count
        or markdown_false_positive_review_queue_count
        or markdown_quality_spot_check_required
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
                    "coverage_strata_targets": _ensure_mapping(
                        markdown_summary.get("coverage_strata_targets")
                    ),
                    "coverage_strata_missing": _ensure_list(
                        markdown_summary.get("coverage_strata_missing")
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
                    "industry_report_count": int(
                        markdown_summary.get("industry_report_count") or 0
                    ),
                    "stock_report_count": int(
                        markdown_summary.get("stock_report_count") or 0
                    ),
                    "stock_outcome_120d_ready_report_count": int(
                        markdown_summary.get("stock_outcome_120d_ready_report_count")
                        or 0
                    ),
                    "stock_outcome_age_bucket_counts": _count_mapping_values(
                        _ensure_mapping(
                            markdown_summary.get("stock_outcome_age_bucket_counts")
                        )
                    ),
                    "sector_bucket_coverage_gaps": _ensure_list(
                        markdown_summary.get("sector_bucket_coverage_gaps")
                    ),
                    "sector_bucket_below_min_count": int(
                        markdown_summary.get("sector_bucket_below_min_count") or 0
                    ),
                    "time_bucket_counts": _count_mapping_values(
                        _ensure_mapping(markdown_summary.get("time_bucket_counts"))
                    ),
                    "institution_bucket_counts": _count_mapping_values(
                        _ensure_mapping(
                            markdown_summary.get("institution_bucket_counts")
                        )
                    ),
                    "report_horizon_bucket_counts": _count_mapping_values(
                        _ensure_mapping(
                            markdown_summary.get("report_horizon_bucket_counts")
                        )
                    ),
                    "evaluability_bucket_counts": _count_mapping_values(
                        _ensure_mapping(
                            markdown_summary.get("evaluability_bucket_counts")
                        )
                    ),
                    "markdown_quality_review_queue_count": (
                        markdown_quality_review_queue_count
                    ),
                    "markdown_false_positive_review_queue_count": (
                        markdown_false_positive_review_queue_count
                    ),
                    "markdown_quality_spot_check_required": (
                        markdown_quality_spot_check_required
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
    recipe_paper_trading_summary = _read_registry_json(
        registry_path / "recipe_paper_trading_summary.json",
        label="recipe_paper_trading_summary",
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
        recipe_paper_trading_summary=recipe_paper_trading_summary,
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
            survivorship_check = str(label.get("survivorship_check") or "").strip()
            if survivorship_check not in STOCK_PRICE_PROXY_SURVIVORSHIP_CHECKS:
                outcome_failures.append(
                    f"{label_id}: stock survivorship_check must be one of "
                    f"{sorted(STOCK_PRICE_PROXY_SURVIVORSHIP_CHECKS)}"
                )
            elif (
                label.get("survivorship_safe") is True
                and survivorship_check
                != STOCK_PRICE_PROXY_SURVIVORSHIP_AUDITED_CHECK
            ):
                outcome_failures.append(
                    f"{label_id}: stock survivorship_safe=true requires "
                    f"{STOCK_PRICE_PROXY_SURVIVORSHIP_AUDITED_CHECK}"
                )
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
            if label.get("entry_tradable") is not True:
                outcome_failures.append(
                    f"{label_id}: stock entry_tradable must be true for generated labels"
                )
            if label.get("exit_tradable") is not True:
                outcome_failures.append(
                    f"{label_id}: stock exit_tradable must be true for generated labels"
                )
            if label.get("entry_limit_locked") is not False:
                outcome_failures.append(
                    f"{label_id}: stock entry_limit_locked must be false for generated labels"
                )
            if label.get("exit_limit_locked") is not False:
                outcome_failures.append(
                    f"{label_id}: stock exit_limit_locked must be false for generated labels"
                )
            if label.get("entry_liquidity_check") != STOCK_PRICE_PROXY_TRADABILITY_CHECK:
                outcome_failures.append(
                    f"{label_id}: stock entry_liquidity_check must be "
                    f"{STOCK_PRICE_PROXY_TRADABILITY_CHECK}"
                )
            if label.get("exit_liquidity_check") != STOCK_PRICE_PROXY_TRADABILITY_CHECK:
                outcome_failures.append(
                    f"{label_id}: stock exit_liquidity_check must be "
                    f"{STOCK_PRICE_PROXY_TRADABILITY_CHECK}"
                )
            forbidden_stock_gaps = {
                "stock_entry_suspended",
                "entry_liquidity_unverified",
                "exit_liquidity_unverified",
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
    proxy_pending_claim_ids = {
        str(claim_id)
        for claim_id in _ensure_list(
            _ensure_mapping(outcome_labeling_readiness).get(
                "proxy_label_pending_only_forecast_claim_ids"
            )
        )
        if str(claim_id).strip()
    }
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
                and claim_id not in proxy_pending_claim_ids
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
                "proxy_label_pending_only_count": len(proxy_pending_claim_ids),
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
            "retired",
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
    for gap_id, gap in tool_gap_by_id.items():
        if str(gap.get("status") or "") == "retired":
            continue
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
    for gap_id, gap in tool_gap_by_id.items():
        if str(gap.get("status") or "") == "retired":
            continue
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
            if (
                step.get("requires_external_tool") is not False
                and str(step.get("tool") or "").strip()
            ):
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
    recipe_paper_trading_summary: Mapping[str, Any] | None = None,
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
    paper_trading_summary = _ensure_mapping(recipe_paper_trading_summary)
    after_cost_paper_trading_summary = _ensure_mapping(
        paper_trading_summary.get("after_cost_paper_trading_summary")
    )
    shadow_paper_trading_run_count = int(
        paper_trading_summary.get("paper_trading_run_count")
        or paper_trading_summary.get("recipe_count")
        or 0
    )
    paper_trading_validation_pass_count = int(
        paper_trading_summary.get("validation_pass_count") or 0
    )
    paper_trading_blocked_count = int(paper_trading_summary.get("blocked_count") or 0)
    after_cost_summary_status = str(
        after_cost_paper_trading_summary.get("status") or ""
    )
    after_cost_positive_recipe_count = int(
        after_cost_paper_trading_summary.get("positive_after_cost_recipe_count") or 0
    )
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
    active_gap_ids = {
        str(row.get("tool_gap_id") or "")
        for row in tool_gap_rows
        if str(row.get("tool_gap_id") or "").strip()
        and str(row.get("status") or "") != "retired"
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
    if not active_gap_ids:
        phase_e_failures.append("tool gap registry must contain reviewable gaps")
    missing_data_proposals = sorted(active_gap_ids - proposal_gap_ids)
    missing_tool_proposals = sorted(active_gap_ids - design_gap_ids)
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
                "active_tool_gap_rows": len(active_gap_ids),
                "retired_tool_gap_rows": len(gap_ids - active_gap_ids),
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
                "registry/report_intelligence/recipe_paper_trading_summary.json",
            ],
            evidence_counts={
                "rollout_mode": rollout_mode,
                "paper_trading_recipe_count": paper_recipe_count,
                "shadow_paper_trading_run_count": shadow_paper_trading_run_count,
                "paper_trading_validation_pass_count": (
                    paper_trading_validation_pass_count
                ),
                "paper_trading_blocked_count": paper_trading_blocked_count,
                "after_cost_summary_status": after_cost_summary_status,
                "after_cost_positive_recipe_count": after_cost_positive_recipe_count,
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
                "registry/report_intelligence/recipe_paper_trading_summary.json",
            ],
            evidence_counts={
                "rollout_mode": rollout_mode,
                "paper_trading_recipe_count": paper_recipe_count,
                "shadow_paper_trading_run_count": shadow_paper_trading_run_count,
                "paper_trading_validation_pass_count": (
                    paper_trading_validation_pass_count
                ),
                "paper_trading_blocked_count": paper_trading_blocked_count,
                "after_cost_summary_status": after_cost_summary_status,
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
    extraction_report = _read_registry_json(
        registry_path / "extraction_report.json",
        label="extraction_report",
        blockers=[],
    )
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
    recipe_paper_trading_summary = _read_registry_json(
        registry_path / "recipe_paper_trading_summary.json",
        label="recipe_paper_trading_summary",
        blockers=[],
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
    count_only_public_fallbacks: list[str] = []
    metadata_rows = _patch_coverage_count_only_rows(
        rows=metadata_rows,
        extraction_report=extraction_report,
        count_field="metadata_rows",
        row_id_field="source_id",
        fallback_label="report_metadata",
        count_only_public_fallbacks=count_only_public_fallbacks,
    )
    forecast_rows = _patch_coverage_count_only_rows(
        rows=forecast_rows,
        extraction_report=extraction_report,
        count_field="forecast_claim_rows",
        row_id_field="forecast_claim_id",
        fallback_label="forecast_claims",
        count_only_public_fallbacks=count_only_public_fallbacks,
    )
    footprint_rows = _patch_coverage_count_only_rows(
        rows=footprint_rows,
        extraction_report=extraction_report,
        count_field="analytical_footprint_rows",
        row_id_field="footprint_id",
        fallback_label="analytical_footprints",
        count_only_public_fallbacks=count_only_public_fallbacks,
    )
    outcome_label_rows = _patch_coverage_count_only_rows(
        rows=outcome_label_rows,
        extraction_report=extraction_report,
        count_field="outcome_label_rows",
        row_id_field="outcome_id",
        fallback_label="report_outcome_labels",
        count_only_public_fallbacks=count_only_public_fallbacks,
    )
    if count_only_public_fallbacks:
        blockers = [
            blocker
            for blocker in blockers
            if not any(
                blocker == f"{label}: missing"
                for label in count_only_public_fallbacks
            )
        ]
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
        recipe_paper_trading_summary=recipe_paper_trading_summary,
    )
    if count_only_public_fallbacks:
        report = dict(report)
        report["count_only_public_fallbacks"] = sorted(count_only_public_fallbacks)
        report["private_input_fallback_policy"] = (
            "When private report JSONL inputs are absent or truncated, this public "
            "coverage artifact uses aggregate counts from extraction_report.json; "
            "synthetic count-only rows contain no source prose, titles, abstracts, "
            "URLs, source spans, or reviewer text."
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


def _patch_coverage_count_only_rows(
    *,
    rows: Sequence[Mapping[str, Any]],
    extraction_report: Mapping[str, Any],
    count_field: str,
    row_id_field: str,
    fallback_label: str,
    count_only_public_fallbacks: list[str],
) -> list[Mapping[str, Any]]:
    public_count = _int_or_none(extraction_report.get(count_field)) or 0
    if public_count <= len(rows):
        return list(rows)
    count_only_public_fallbacks.append(fallback_label)
    return [
        {row_id_field: f"COUNT-ONLY-{fallback_label}-{index:06d}"}
        for index in range(1, public_count + 1)
    ]


def _append_unique_records(
    target: list[dict[str, Any]],
    records: Sequence[dict[str, Any]],
    *,
    key: str,
    replace_existing: bool = False,
) -> None:
    seen = {
        str(record.get(key) or ""): index
        for index, record in enumerate(target)
        if str(record.get(key) or "")
    }
    for record in records:
        value = str(record.get(key) or "")
        if not value:
            continue
        if value in seen:
            if replace_existing:
                target[seen[value]] = record
            continue
        target.append(record)
        seen[value] = len(target) - 1


METHOD_PATTERN_MERGE_LIST_FIELDS = (
    "source_footprint_ids",
    "steps",
    "required_current_data",
    "optional_confirmation_data",
    "failure_modes",
    "target_agents",
)


def _method_pattern_canonical_name(record: Mapping[str, Any]) -> str:
    return (
        str(record.get("canonical_name") or "").strip()
        or _canonical_metric_name(record.get("name"))
    )


def _canonicalize_method_pattern_record(record: Mapping[str, Any]) -> dict[str, Any]:
    canonical = _method_pattern_canonical_name(record)
    normalized = dict(record)
    if canonical:
        normalized["canonical_name"] = canonical
        normalized["method_pattern_id"] = _stable_id(
            "METHOD",
            {"canonical_name": canonical},
        )
    return normalized


def _method_pattern_identity_keys(record: Mapping[str, Any]) -> list[str]:
    keys: list[str] = []
    method_id = str(record.get("method_pattern_id") or "").strip()
    if method_id:
        keys.append(f"id:{method_id}")
    canonical = _method_pattern_canonical_name(record)
    if canonical:
        keys.append(f"canonical:{canonical}")
    return keys


def _merge_method_pattern_record(
    existing: Mapping[str, Any],
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    existing = _canonicalize_method_pattern_record(existing)
    incoming = _canonicalize_method_pattern_record(incoming)
    merged = dict(existing)
    for field in METHOD_PATTERN_MERGE_LIST_FIELDS:
        merged[field] = _merge_unique_values(
            _ensure_list(existing.get(field)),
            _ensure_list(incoming.get(field)),
        )
    for field in (
        "name",
        "description",
        "validation_status",
        "allowed_runtime_mode",
    ):
        if not str(merged.get(field) or "").strip() and incoming.get(field) is not None:
            merged[field] = incoming.get(field)
    if not _ensure_mapping(merged.get("extractor")) and _ensure_mapping(
        incoming.get("extractor")
    ):
        merged["extractor"] = dict(_ensure_mapping(incoming.get("extractor")))
    return _canonicalize_method_pattern_record(merged)


def _append_unique_method_patterns(
    target: list[dict[str, Any]],
    records: Sequence[dict[str, Any]],
    *,
    replace_existing: bool = False,
) -> None:
    compacted: list[dict[str, Any]] = []
    seen: dict[str, int] = {}

    def append_one(record: Mapping[str, Any], *, replace: bool) -> None:
        normalized = _canonicalize_method_pattern_record(record)
        if not str(normalized.get("method_pattern_id") or "").strip():
            return
        keys = _method_pattern_identity_keys(normalized)
        existing_indexes = [seen[key] for key in keys if key in seen]
        if existing_indexes:
            index = min(existing_indexes)
            if replace:
                compacted[index] = normalized
            else:
                compacted[index] = _merge_method_pattern_record(
                    compacted[index],
                    normalized,
            )
            for key in _method_pattern_identity_keys(compacted[index]):
                seen[key] = index
            return
        compacted.append(normalized)
        index = len(compacted) - 1
        for key in keys:
            seen[key] = index

    for record in target:
        append_one(record, replace=False)
    for record in records:
        append_one(record, replace=replace_existing)
    target[:] = compacted


REPORT_INTELLIGENCE_BATCH_MERGE_JSONL_KEYS: Mapping[str, str] = {
    "analytical_footprints.jsonl": "footprint_id",
    "forecast_claims.jsonl": "forecast_claim_id",
    "metric_candidates.jsonl": "metric_candidate_id",
    "method_patterns.jsonl": "method_pattern_id",
    "processing_status.jsonl": "source_id",
    "report_metadata.jsonl": "report_id",
    "report_outcome_labels.jsonl": "outcome_label_id",
    "tool_gaps.jsonl": "tool_gap_id",
    "weighted_research_contexts.jsonl": "context_id",
}


def _batch_output_path(input_dir: Path, filename: str) -> Path:
    direct = input_dir / filename
    if direct.exists():
        return direct
    nested = input_dir / "registry/report_intelligence" / filename
    if nested.exists():
        return nested
    return direct


def merge_report_intelligence_batch_outputs(
    *,
    root: str | Path = ".",
    input_dirs: Sequence[str | Path],
    registry_dir: str | Path = REPORT_INTELLIGENCE_REGISTRY_DIR,
    include_existing_registry: bool = True,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    registry_path = (
        Path(registry_dir)
        if Path(registry_dir).is_absolute()
        else root_path / registry_dir
    )
    resolved_inputs = [
        Path(input_dir) if Path(input_dir).is_absolute() else root_path / input_dir
        for input_dir in input_dirs
    ]
    blockers: list[str] = []
    outputs: dict[str, str] = {}
    row_counts: dict[str, int] = {}
    input_file_counts: dict[str, int] = {}
    existing_file_counts: dict[str, int] = {}
    for filename, key in REPORT_INTELLIGENCE_BATCH_MERGE_JSONL_KEYS.items():
        replace_duplicates = filename in {
            "processing_status.jsonl",
            "report_metadata.jsonl",
        }
        rows: list[dict[str, Any]] = []
        existing_file_count = 0
        existing_path = registry_path / filename
        if include_existing_registry and existing_path.exists():
            existing_file_count = 1
            existing_rows = _read_registry_jsonl(
                existing_path,
                label=f"{registry_path.name}/{filename}",
                blockers=blockers,
            )
            if filename == "method_patterns.jsonl":
                _append_unique_method_patterns(
                    rows,
                    [dict(row) for row in existing_rows],
                    replace_existing=replace_duplicates,
                )
            else:
                _append_unique_records(
                    rows,
                    [dict(row) for row in existing_rows],
                    key=key,
                    replace_existing=replace_duplicates,
                )
        file_count = 0
        for input_dir in resolved_inputs:
            path = _batch_output_path(input_dir, filename)
            if not path.exists():
                continue
            file_count += 1
            batch_rows = _read_registry_jsonl(
                path,
                label=f"{input_dir.name}/{filename}",
                blockers=blockers,
            )
            if filename == "method_patterns.jsonl":
                _append_unique_method_patterns(
                    rows,
                    [dict(row) for row in batch_rows],
                    replace_existing=replace_duplicates,
                )
            else:
                _append_unique_records(
                    rows,
                    [dict(row) for row in batch_rows],
                    key=key,
                    replace_existing=replace_duplicates,
                )
        if file_count:
            written = _write_jsonl(registry_path / filename, rows)
            outputs[filename] = str(written["path"])
            row_counts[filename] = len(rows)
            input_file_counts[filename] = file_count
            existing_file_counts[filename] = existing_file_count
    if not outputs:
        blockers.append("no report-intelligence batch jsonl files found")
    return {
        "input_dirs": [str(path) for path in resolved_inputs],
        "input_dir_count": len(resolved_inputs),
        "include_existing_registry": include_existing_registry,
        "outputs": outputs,
        "row_counts": row_counts,
        "input_file_counts": input_file_counts,
        "existing_file_counts": existing_file_counts,
        "blockers": blockers,
        "blocker_count": len(blockers),
    }


def _extract_for_markdown(
    row: Mapping[str, Any],
    markdown_text: str,
    *,
    run_id: str,
    extractor: LlmExtractor,
    chunk_chars: int,
    max_chunks: int,
    macro_regime_calendar_rows: Sequence[Mapping[str, Any]] = (),
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
                macro_regime_calendar_rows=macro_regime_calendar_rows,
            ),
            key="forecast_claim_id",
        )
        _append_unique_records(all_footprints, footprints, key="footprint_id")
        _append_unique_records(all_metrics, metrics, key="metric_candidate_id")
        _append_unique_method_patterns(all_methods, methods)
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
    macro_regime_calendar_rows = _read_macro_regime_calendar_rows(registry_dir)
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
    forecast_rows = _refresh_forecast_mapping_governance(
        forecast_rows,
        macro_regime_calendar_rows=macro_regime_calendar_rows,
    )
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
    _append_unique_method_patterns(
        method_rows,
        _normalize_method_patterns(
            {},
            footprint_rows,
            run_id=run_id,
            model="derived_refresh",
        ),
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
        forecast_rows=forecast_rows,
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
    industry_etf_proxy_pit_availability = _with_industry_pit_labelability_summary(
        industry_etf_proxy_pit_availability,
        industry_etf_proxy_readiness,
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
        macro_regime_calendar_rows=macro_regime_calendar_rows,
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
        forecast_rows=forecast_rows,
        footprint_rows=footprint_rows,
        method_rows=method_rows,
    )
    recipe_paper_trading_summary = build_recipe_paper_trading_summary(
        run_id=run_id,
        recipe_paper_trading_runs=recipe_paper_trading_run_rows,
        tool_gap_rows=tool_gap_rows,
        tool_design_proposal_rows=tool_design_proposal_rows,
        direct_pit_binding_gap_details=_direct_pit_binding_gap_details(
            analysis_recipe_rows=analysis_recipe_rows,
            outcome_label_rows=outcome_label_rows,
            forecast_rows=forecast_rows,
            footprint_rows=footprint_rows,
            method_rows=method_rows,
        ),
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
        recipe_paper_trading_summary=recipe_paper_trading_summary,
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
        preserve_existing_summary=True,
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
            recipe_paper_trading_summary=recipe_paper_trading_summary,
        )
    )
    schema_validation_report = _read_schema_validation_report(root_path)
    evolution_history = _prepare_evolution_refresh_history(
        registry_dir=registry_dir,
        run_id=run_id,
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_label_rows,
        recipe_paper_trading_summary=recipe_paper_trading_summary,
        confidence_impact_monitor=confidence_impact_monitor,
        markdown_coverage_summary=markdown_coverage_summary,
        schema_validation_report=schema_validation_report,
        pit_leakage_audit=pit_leakage_audit,
        extraction_provenance_audit=extraction_provenance_audit,
        statistical_robustness_audit=statistical_robustness_audit,
        gold_review_summary=gold_review_summary,
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
        recipe_paper_trading_summary=recipe_paper_trading_summary,
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
        "method_patterns": str(
            _write_jsonl(registry_dir / "method_patterns.jsonl", method_rows)["path"]
        ),
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
    processed_source_ids, processed_source_blockers = _processed_source_ids_from_registry_dirs(
        root_path,
        cfg.exclude_processed_registry_dirs,
    )
    rows, source_blockers = _selected_source_rows(
        root_path,
        source_path=cfg.source_path,
        cache_dir=cfg.cache_dir,
        source_ids=cfg.source_ids,
        exclude_source_ids=tuple(processed_source_ids),
        require_cached_markdown=cfg.require_cached_markdown,
        limit=cfg.limit,
        min_publish_date=cfg.min_publish_date,
        max_publish_date=cfg.max_publish_date,
        selection_order=cfg.selection_order,
    )
    blockers: list[str] = [*processed_source_blockers, *source_blockers]
    macro_regime_calendar_rows = _read_macro_regime_calendar_rows(registry_dir)
    _emit_report_intelligence_progress(
        cfg,
        event="selected",
        run_id=run_id,
        selected_reports=len(rows),
        excluded_processed_count=len(processed_source_ids),
        source_blocker_count=len(source_blockers),
    )
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
            api_key=cfg.vllm_api_key,
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
    for index, row in enumerate(rows, 1):
        _emit_report_intelligence_progress(
            cfg,
            event="row_prepare_start",
            run_id=run_id,
            index=index,
            total=len(rows),
            skip_download=cfg.skip_download,
            skip_convert=cfg.skip_convert,
            skip_llm=cfg.skip_llm,
        )
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
                "index": index,
                "source_id": source_id,
                "pdf_path": pdf_path,
                "markdown_path": markdown_path,
                "mineru_output_dir": mineru_output_dir,
                "pdf_result": pdf_result,
                "markdown_result": {"status": "not_attempted"},
                "row_blockers": row_blockers,
            }
        )
        _emit_report_intelligence_progress(
            cfg,
            event="row_prepare_done",
            run_id=run_id,
            index=index,
            total=len(rows),
            pdf_status=str(pdf_result.get("status") or "not_attempted"),
            blocker_count=len(row_blockers),
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
        index = int(prepared.get("index") or 0)
        _emit_report_intelligence_progress(
            cfg,
            event="row_extract_start",
            run_id=run_id,
            index=index,
            total=len(prepared_rows),
        )
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
                    markdown_text = markdown_path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )
                    _emit_report_intelligence_progress(
                        cfg,
                        event="llm_start",
                        run_id=run_id,
                        index=index,
                        total=len(prepared_rows),
                        markdown_bytes=markdown_path.stat().st_size,
                        chunk_chars=cfg.chunk_chars,
                        max_chunks=cfg.max_chunks,
                    )
                    extraction, llm_status, llm_model, llm_blockers, chunk_count, truncated_chunks = (
                        _extract_for_markdown(
                            row,
                            markdown_text,
                            run_id=run_id,
                            extractor=llm_extractor,
                            chunk_chars=cfg.chunk_chars,
                            max_chunks=cfg.max_chunks,
                            macro_regime_calendar_rows=macro_regime_calendar_rows,
                        )
                    )
                    _emit_report_intelligence_progress(
                        cfg,
                        event="llm_done",
                        run_id=run_id,
                        index=index,
                        total=len(prepared_rows),
                        llm_status=llm_status,
                        chunk_count=chunk_count,
                        truncated_chunks=truncated_chunks,
                        forecast_claim_count=len(extraction["forecast_claims"]),
                        analytical_footprint_count=len(
                            extraction["analytical_footprints"]
                        ),
                        tool_gap_count=len(extraction["tool_gaps"]),
                        blocker_count=len(llm_blockers),
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
                    _append_unique_method_patterns(
                        method_rows,
                        extraction["method_patterns"],
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
        _emit_report_intelligence_progress(
            cfg,
            event="row_done",
            run_id=run_id,
            index=index,
            total=len(prepared_rows),
            pdf_status=str(pdf_result.get("status") or "not_attempted"),
            markdown_status=str(markdown_result.get("status") or "not_attempted"),
            markdown_quality_gate_status=str(
                markdown_result.get("quality_gate_status") or ""
            ),
            llm_status=llm_status,
            blocker_count=len(row_blockers),
        )

    forecast_rows = _refresh_forecast_mapping_governance(
        forecast_rows,
        macro_regime_calendar_rows=macro_regime_calendar_rows,
    )
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
        forecast_rows=forecast_rows,
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
    industry_etf_proxy_pit_availability = _with_industry_pit_labelability_summary(
        industry_etf_proxy_pit_availability,
        industry_etf_proxy_readiness,
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
        macro_regime_calendar_rows=macro_regime_calendar_rows,
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
        forecast_rows=forecast_rows,
        footprint_rows=footprint_rows,
        method_rows=method_rows,
    )
    recipe_paper_trading_summary = build_recipe_paper_trading_summary(
        run_id=run_id,
        recipe_paper_trading_runs=recipe_paper_trading_run_rows,
        tool_gap_rows=tool_gap_rows,
        tool_design_proposal_rows=tool_design_proposal_rows,
        direct_pit_binding_gap_details=_direct_pit_binding_gap_details(
            analysis_recipe_rows=analysis_recipe_rows,
            outcome_label_rows=outcome_label_rows,
            forecast_rows=forecast_rows,
            footprint_rows=footprint_rows,
            method_rows=method_rows,
        ),
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
        recipe_paper_trading_summary=recipe_paper_trading_summary,
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
            recipe_paper_trading_summary=recipe_paper_trading_summary,
        )
    )
    schema_validation_report = _read_schema_validation_report(root_path)
    evolution_history = _prepare_evolution_refresh_history(
        registry_dir=registry_dir,
        run_id=run_id,
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_label_rows,
        recipe_paper_trading_summary=recipe_paper_trading_summary,
        confidence_impact_monitor=confidence_impact_monitor,
        markdown_coverage_summary=markdown_coverage_summary,
        schema_validation_report=schema_validation_report,
        pit_leakage_audit=pit_leakage_audit,
        extraction_provenance_audit=extraction_provenance_audit,
        statistical_robustness_audit=statistical_robustness_audit,
        gold_review_summary=gold_review_summary,
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
        recipe_paper_trading_summary=recipe_paper_trading_summary,
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
    _emit_report_intelligence_progress(
        cfg,
        event="summary",
        run_id=run_id,
        selected_reports=summary.selected_reports,
        llm_processed_reports=summary.llm_processed_reports,
        forecast_claim_rows=summary.forecast_claim_rows,
        outcome_label_rows=summary.outcome_label_rows,
        blocker_count=summary.blocker_count,
    )
    return summary
