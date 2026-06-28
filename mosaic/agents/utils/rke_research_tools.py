"""LangChain tools for public-safe RKE research context.

These tools expose only the redacted agent-facing view. Full report prose,
source spans, local PDF/Markdown paths, and review notes stay inside the
private report-intelligence registry.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from mosaic.rke.agent_research_context import (
    build_rke_agent_research_context,
    format_rke_agent_research_context,
)


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
    return format_rke_agent_research_context(context)
