"""Master-plan final acceptance mapping for the RKE completion audit."""

from __future__ import annotations

from typing import Any


MASTER_PLAN_PATH = "docs/plans/master_plan_v1_1.md"
MASTER_PLAN_ACCEPTANCE_SECTION = "22"
EXPECTED_COMPLETION_CRITERION_IDS = tuple(f"C{index:02d}" for index in range(1, 13))

FINAL_ACCEPTANCE_REQUIREMENTS: tuple[dict[str, str], ...] = (
    {
        "criterion_id": "C01",
        "requirement": "At least one macro rule family reaches Phase -1 through Phase 4.",
    },
    {
        "criterion_id": "C02",
        "requirement": "Claim extraction gold set passes the manual gate.",
    },
    {
        "criterion_id": "C03",
        "requirement": "Data availability matrix covers the first production candidate proxies.",
    },
    {
        "criterion_id": "C04",
        "requirement": "Validation v2 reports effective N, overlap, multiple testing, and costs.",
    },
    {
        "criterion_id": "C05",
        "requirement": "Runtime rule aggregation implements correlated-rule de-dup and conflict objects.",
    },
    {
        "criterion_id": "C06",
        "requirement": "Confidence policy v1 implements the min-components safe function.",
    },
    {
        "criterion_id": "C07",
        "requirement": "Research-only no-trade rule is enforced by checker.",
    },
    {
        "criterion_id": "C08",
        "requirement": "Patch validator rejects forbidden paths and inconsistent target paths.",
    },
    {
        "criterion_id": "C09",
        "requirement": "Paper trading monitor outputs live-vs-baseline differences.",
    },
    {
        "criterion_id": "C10",
        "requirement": "Production monitor detects alpha decay and calibration drift.",
    },
    {
        "criterion_id": "C11",
        "requirement": "Compliance gate blocks unauthorized reports from production runtime.",
    },
    {
        "criterion_id": "C12",
        "requirement": "Audit viewer traces source to claim to hypothesis to rule to parameter to experiment to patch to agent output.",
    },
)


def final_acceptance_metadata() -> dict[str, Any]:
    return {
        "master_plan_path": MASTER_PLAN_PATH,
        "acceptance_section": MASTER_PLAN_ACCEPTANCE_SECTION,
        "acceptance_criteria_count": len(FINAL_ACCEPTANCE_REQUIREMENTS),
        "acceptance_requirements": [
            dict(item) for item in FINAL_ACCEPTANCE_REQUIREMENTS
        ],
    }
