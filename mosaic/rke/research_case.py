"""The source-derived research argument kept inside an analytical footprint."""

from collections.abc import Mapping
from typing import Any


CASE_TEXT_FIELDS = ("question", "historical_regime", "conclusion")
CASE_LIST_FIELDS = (
    "reasoning_chain", "evidence", "assumptions", "invalidation_conditions",
)


def normalize_research_case(value: Any) -> dict[str, Any] | None:
    """Select the case contract; never manufacture missing reasoning or conditions."""
    if not isinstance(value, Mapping):
        return None
    result: dict[str, Any] = {}
    for field in CASE_TEXT_FIELDS:
        text = value.get(field, "")
        if field == "historical_regime" and isinstance(text, list):
            if any(not isinstance(item, str) for item in text):
                return None
            text = "；".join(item.strip() for item in text if item.strip())
        if not isinstance(text, str):
            return None
        result[field] = text.strip()
    for field in CASE_LIST_FIELDS:
        items = value.get(field, [])
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
            return None
        result[field] = [item.strip() for item in items if item.strip()]
    if not result["question"] or not result["reasoning_chain"]:
        return None
    if all(step == result["question"] for step in result["reasoning_chain"]):
        return None
    return result


def recover_legacy_research_case(footprint: Mapping[str, Any]) -> dict[str, Any] | None:
    """Recover one explicit legacy argument, without joining unrelated patterns."""
    patterns = footprint.get("analysis_patterns", [])
    if not isinstance(patterns, list) or len(patterns) != 1:
        return None
    pattern = patterns[0]
    if not isinstance(pattern, Mapping) or pattern.get("source_grounded") is False:
        return None
    raw_steps = pattern.get("steps", [])
    if not isinstance(raw_steps, list):
        return None
    steps = []
    for step in raw_steps:
        if isinstance(step, Mapping):
            if step.get("source_grounded") is False:
                return None
            step = step.get("description") or step.get("step_description") or step.get("step")
        if not isinstance(step, str) or not step.strip():
            return None
        steps.append(step.strip())
    if len(steps) < 2:
        return None
    conditions = pattern.get("failure_modes", [])
    if isinstance(conditions, str):
        conditions = [conditions] if conditions.strip() else []
    return normalize_research_case({
        "question": footprint.get("topic", ""),
        "reasoning_chain": steps,
        "invalidation_conditions": conditions,
    })


def research_case_method_identity(case: Mapping[str, Any]) -> dict[str, Any]:
    """Keep distinct mechanisms and conditions distinct, independent of source IDs."""
    return {field: case.get(field) for field in (
        "question", "historical_regime", "reasoning_chain", "assumptions",
        "invalidation_conditions", "conclusion",
    )}
