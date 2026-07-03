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
    RANKING_POLICY_ID,
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
    lines.extend(["", format_rke_agent_research_context(context)])
    return "\n".join(lines)


def _runtime_preflight(context: Mapping[str, Any]) -> dict[str, Any]:
    items = [
        item for item in (context.get("context_items") or []) if isinstance(item, Mapping)
    ]
    ranks = [item.get("retrieval_rank") for item in items]
    priority_buckets = [str(item.get("priority_bucket") or "") for item in items]
    failures: list[str] = []
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
    if context.get("production_signal_allowed") is not False:
        failures.append("production_signal_not_disabled")
    summary = context.get("summary")
    summary_map = summary if isinstance(summary, Mapping) else {}
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
        "truncated_item_count": int(summary_map.get("truncated_item_count") or 0),
        "current_data_required": summary_map.get("current_data_required") is True,
    }


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
