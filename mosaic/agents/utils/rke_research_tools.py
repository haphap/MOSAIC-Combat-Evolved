"""LangChain tools for public-safe RKE research context.

These tools expose only the redacted agent-facing view. Full report prose,
source spans, local PDF/Markdown paths, and review notes stay inside the
private report-intelligence registry.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from typing import Any
from typing import Mapping

from langchain_core.tools import tool

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.rke.agent_research_context import (
    FORBIDDEN_FIELD_POLICY,
    RESEARCH_PRIOR_USE_POLICY,
    SAFE_ACTIONABILITY,
    SCHEMA_VERSION,
    assert_public_safe_context,
    build_rke_agent_research_context,
    format_rke_agent_research_context,
    normalize_agent_id,
)

def format_rke_runtime_context(context: Mapping[str, Any]) -> str:
    """Format RKE context with the runtime audit required before agent use."""
    failures = _runtime_preflight(context)
    if failures:
        raise DataVendorUnavailable(
            "RKE context preflight failed: " + ", ".join(failures),
            reason_code="RKE_CONTEXT_PREFLIGHT_FAILED",
        )
    return format_rke_agent_research_context(context)


def _runtime_preflight(context: Mapping[str, Any]) -> list[str]:
    raw_items = context.get("context_items")
    item_values = raw_items if isinstance(raw_items, (list, tuple)) else []
    items = [item for item in item_values if isinstance(item, Mapping)]
    failures: list[str] = []
    if raw_items is None:
        failures.append("context_items_missing")
    elif not isinstance(raw_items, (list, tuple)):
        failures.append("context_items_malformed")
    elif len(items) != len(item_values):
        failures.append("context_item_not_object")
    agent_id = str(context.get("agent_id") or "")
    layer = str(context.get("layer") or "")
    if not agent_id:
        failures.append("agent_id_missing")
    requested_agent_id = str(context.get("requested_agent_id") or "")
    if not requested_agent_id:
        failures.append("requested_agent_id_missing")
    elif agent_id and normalize_agent_id(requested_agent_id, layer=layer) != agent_id:
        failures.append("requested_agent_id_mismatch")
    if not layer:
        failures.append("layer_missing")
    elif agent_id and "." in agent_id and layer != agent_id.split(".", 1)[0]:
        failures.append("layer_agent_mismatch")
    as_of_date = str(context.get("as_of_date") or "")
    if not as_of_date:
        failures.append("as_of_date_missing")
    else:
        try:
            date.fromisoformat(as_of_date)
        except ValueError:
            failures.append("as_of_date_invalid")
    schema_version = str(context.get("schema_version") or "")
    if not schema_version:
        failures.append("schema_version_missing")
    elif schema_version != SCHEMA_VERSION:
        failures.append("schema_version_mismatch")
    if items and any(not item.get("redacted_claim_id") for item in items):
        failures.append("redacted_claim_id_missing")
    if items and any(
        not item.get(field)
        for item in items
        for field in ("target_type", "target_id", "metric_family")
    ):
        failures.append("item_target_metadata_missing")
    if items and any(
        not item.get(field)
        for item in items
        for field in ("expected_direction", "horizon_bucket", "regime_bucket")
    ):
        failures.append("item_context_metadata_missing")
    if items and any(
        not isinstance(item.get("regime_types"), (list, tuple))
        or not all(isinstance(tag, str) and tag for tag in item.get("regime_types", []))
        for item in items
    ):
        failures.append("item_regime_types_invalid")
    if agent_id.startswith("superinvestor.") and items and any(
        not isinstance(item.get("role_filter_reason_codes"), (list, tuple))
        or not any(
            isinstance(reason, str) and reason.startswith("role_filter_")
            for reason in item.get("role_filter_reason_codes", [])
        )
        for item in items
    ):
        failures.append("superinvestor_role_filter_missing")
    if items and any(item.get("current_data_required") is not True for item in items):
        failures.append("current_data_required_missing")
    if items and any(
        not isinstance(item.get("current_data_required_fields"), (list, tuple))
        or not item.get("current_data_required_fields")
        or not all(
            isinstance(field, str) and field
            for field in item.get("current_data_required_fields", [])
        )
        for item in items
    ):
        failures.append("current_data_required_fields_invalid")
    if items and any(item.get("production_signal_allowed") is not False for item in items):
        failures.append("item_production_signal_not_disabled")
    if items and any(item.get("use_policy") != RESEARCH_PRIOR_USE_POLICY for item in items):
        failures.append("item_use_policy_invalid")
    if items and any(item.get("actionability") != SAFE_ACTIONABILITY for item in items):
        failures.append("item_actionability_invalid")
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
    if not items and not summary_map.get("no_prior_reason"):
        failures.append("no_prior_reason_missing")
    for item in items:
        try:
            available = date.fromisoformat(item.get("available_date"))
        except (TypeError, ValueError):
            failures.append("item_available_date_invalid")
            break
        if available.isoformat() > as_of_date:
            failures.append("item_available_date_after_as_of")
            break
    return failures


@tool
def get_rke_research_context(
    agent_id: Annotated[
        str,
        "MOSAIC agent id, e.g. 'us_financial_conditions', "
        "'macro.us_financial_conditions', 'semiconductor', "
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
