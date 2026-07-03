"""LangChain tools for public-safe RKE research context.

These tools expose only the redacted agent-facing view. Full report prose,
source spans, local PDF/Markdown paths, and review notes stay inside the
private report-intelligence registry.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated
from typing import Any
from typing import Mapping

from langchain_core.tools import tool

from mosaic.rke.agent_research_context import (
    FORBIDDEN_FIELD_POLICY,
    RANKING_POLICY_ID,
    RESEARCH_PRIOR_USE_POLICY,
    SAFE_ACTIONABILITY,
    SCHEMA_VERSION,
    assert_public_safe_context,
    build_rke_agent_research_context,
    format_rke_agent_research_context,
)

_PRIORITY_BUCKETS = frozenset({"high", "medium", "low"})


def format_rke_runtime_context(context: Mapping[str, Any]) -> str:
    """Format RKE context with the runtime audit required before agent use."""
    audit = _runtime_preflight(context)
    lines = [
        (
            "Runtime preflight: "
            f"runtime_preflight_status={audit['runtime_preflight_status']}; "
            f"ranking_policy_id={audit['ranking_policy_id']}; "
            f"context_hash={audit['context_hash']}; "
            "display_sort_policy=preserve_part1_retrieval_rank"
        ),
        (
            "Runtime ranking audit: "
            f"retrieval_ranks={audit['retrieval_ranks']}; "
            f"priority_buckets={audit['priority_buckets']}; "
            f"truncated_item_count={audit['truncated_item_count']}; "
            f"current_data_required={str(audit['current_data_required']).lower()}"
        ),
    ]
    failures = audit["preflight_failures"]
    if failures:
        lines.append(f"Runtime preflight failures: {', '.join(failures)}")
    if "public_safe_context_violation" in failures:
        lines.extend(["", "RKE context body withheld: public-safe context violation."])
        return "\n".join(lines)
    lines.extend(["", format_rke_agent_research_context(context)])
    return "\n".join(lines)


def _runtime_preflight(context: Mapping[str, Any]) -> dict[str, Any]:
    raw_items = context.get("context_items")
    item_values = raw_items if isinstance(raw_items, (list, tuple)) else []
    items = [item for item in item_values if isinstance(item, Mapping)]
    ranks = [item.get("retrieval_rank") for item in items]
    priority_buckets = [str(item.get("priority_bucket") or "") for item in items]
    failures: list[str] = []
    if raw_items is None:
        failures.append("context_items_missing")
    elif not isinstance(raw_items, (list, tuple)):
        failures.append("context_items_malformed")
    elif len(items) != len(item_values):
        failures.append("context_item_not_object")
    schema_version = str(context.get("schema_version") or "")
    if not schema_version:
        failures.append("schema_version_missing")
    elif schema_version != SCHEMA_VERSION:
        failures.append("schema_version_mismatch")
    ranking_policy_id = str(context.get("ranking_policy_id") or "")
    if not ranking_policy_id:
        failures.append("ranking_policy_id_missing")
    elif ranking_policy_id != RANKING_POLICY_ID:
        failures.append("ranking_policy_id_mismatch")
    rank_numbers = [
        rank
        for rank in ranks
        if isinstance(rank, int) and not isinstance(rank, bool) and rank > 0
    ]
    if len(rank_numbers) != len(ranks):
        failures.append("retrieval_rank_missing")
    elif rank_numbers != sorted(rank_numbers):
        failures.append("retrieval_rank_order_changed")
    if any(not bucket for bucket in priority_buckets):
        failures.append("priority_bucket_missing")
    elif any(bucket not in _PRIORITY_BUCKETS for bucket in priority_buckets):
        failures.append("priority_bucket_unsupported")
    if items and any(not item.get("ranking_reason_codes") for item in items):
        failures.append("ranking_reason_codes_missing")
    if items and any(item.get("current_data_required") is not True for item in items):
        failures.append("current_data_required_missing")
    if items and any(not item.get("current_data_required_fields") for item in items):
        failures.append("current_data_required_fields_missing")
    if items and any(item.get("production_signal_allowed") is not False for item in items):
        failures.append("item_production_signal_not_disabled")
    if items and any(item.get("use_policy") != RESEARCH_PRIOR_USE_POLICY for item in items):
        failures.append("item_use_policy_invalid")
    if items and any(item.get("actionability_guard") != SAFE_ACTIONABILITY for item in items):
        failures.append("item_actionability_guard_invalid")
    if context.get("research_only") is not True:
        failures.append("research_only_missing")
    if context.get("actionability") != SAFE_ACTIONABILITY:
        failures.append("context_actionability_guard_invalid")
    if context.get("production_signal_allowed") is not False:
        failures.append("production_signal_not_disabled")
    summary = context.get("summary")
    summary_map = summary if isinstance(summary, Mapping) else {}
    summary_ranking_policy_id = str(summary_map.get("ranking_policy_id") or "")
    if not summary_ranking_policy_id:
        failures.append("summary_ranking_policy_id_missing")
    elif summary_ranking_policy_id != RANKING_POLICY_ID:
        failures.append("summary_ranking_policy_id_mismatch")
    if summary_map.get("current_data_required") is not True:
        failures.append("summary_current_data_required_missing")
    if summary_map.get("private_text_included") is not False:
        failures.append("private_text_boundary_missing")
    if summary_map.get("forbidden_field_policy") != FORBIDDEN_FIELD_POLICY:
        failures.append("forbidden_field_policy_invalid")
    try:
        assert_public_safe_context(context)
    except ValueError:
        failures.append("public_safe_context_violation")
    item_count = _optional_non_negative_int(summary_map.get("item_count"))
    if item_count is None:
        failures.append("item_count_invalid")
    elif item_count != len(items):
        failures.append("item_count_mismatch")
    matched_item_count = _optional_non_negative_int(
        summary_map.get("matched_item_count")
    )
    if matched_item_count is None:
        failures.append("matched_item_count_invalid")
    elif matched_item_count < len(items):
        failures.append("matched_item_count_below_visible")
    truncated_item_count = _optional_non_negative_int(
        summary_map.get("truncated_item_count")
    )
    if (
        summary_map.get("truncated_item_count") is not None
        and truncated_item_count is None
    ):
        failures.append("truncated_item_count_invalid")
    elif matched_item_count is not None and truncated_item_count is not None:
        if matched_item_count - len(items) != truncated_item_count:
            failures.append("truncated_item_count_mismatch")
    return {
        "runtime_preflight_status": "blocked" if failures else "passed",
        "preflight_failures": failures,
        "ranking_policy_id": ranking_policy_id,
        "context_hash": hashlib.sha256(
            json.dumps(
                context,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "retrieval_ranks": ",".join(str(rank) for rank in ranks) or "none",
        "priority_buckets": ",".join(priority_buckets) or "none",
        "truncated_item_count": truncated_item_count or 0,
        "current_data_required": summary_map.get("current_data_required") is True
        and not any(item.get("current_data_required") is not True for item in items),
    }


def _optional_non_negative_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


@tool
def get_rke_research_context(
    agent_id: Annotated[
        str,
        "MOSAIC agent id, e.g. 'dollar', 'macro.dollar', 'semiconductor', "
        "'sector.semiconductor', 'ackman', or 'superinvestor.ackman'.",
    ],
    as_of_date: Annotated[
        str,
        "ISO yyyy-mm-dd date. RKE report-derived priors after this date are excluded.",
    ],
    layer: Annotated[
        str,
        "Optional layer hint: 'macro', 'sector', or 'superinvestor'.",
    ] = "",
    ticker: Annotated[
        str,
        "Optional A-share ticker filter for superinvestor stock context, e.g. '600519.SH'.",
    ] = "",
    sector: Annotated[
        str,
        "Optional sector/industry filter for sector context, e.g. '半导体'.",
    ] = "",
    max_items: Annotated[int, "Maximum redacted context items to return."] = 12,
) -> str:
    """Return public-safe RKE research priors for a MOSAIC agent.

    The output is research-only and cannot be used as a production signal. Agents
    must confirm every RKE prior with current data tools before raising
    confidence or proposing positions.
    """
    context = build_rke_agent_research_context(
        agent_id=agent_id,
        as_of_date=as_of_date,
        layer=layer,
        ticker=ticker,
        sector=sector,
        max_items=max_items,
    )
    return format_rke_runtime_context(context)
