"""Role-scoped PIT tools for the Sector layer."""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from mosaic.dataflows.sector_snapshots import (
    SECTOR_DIRECTION_IDS,
    render_relationship_snapshot,
    render_sector_snapshot,
)


@tool
def get_sector_research_snapshot(
    as_of_date: Annotated[str, "Runtime-owned PIT cutoff in yyyy-mm-dd format."],
    sector_agent_id: Annotated[str, "Runtime-owned standard Sector agent id."],
) -> str:
    """Return the frozen directions, securities, comparable cards, and evidence for one role."""
    if sector_agent_id not in SECTOR_DIRECTION_IDS:
        raise ValueError(f"unknown standard Sector agent {sector_agent_id!r}")
    return render_sector_snapshot(sector_agent_id, as_of_date)


@tool
def get_relationship_research_snapshot(
    as_of_date: Annotated[str, "Runtime-owned PIT cutoff in yyyy-mm-dd format."],
    sector_agent_id: Annotated[str, "Must be relationship_mapper."],
) -> str:
    """Return relationships over the frozen accepted Sector security domain."""
    if sector_agent_id != "relationship_mapper":
        raise ValueError("get_relationship_research_snapshot requires relationship_mapper")
    return render_relationship_snapshot(as_of_date)


__all__ = ["get_relationship_research_snapshot", "get_sector_research_snapshot"]
