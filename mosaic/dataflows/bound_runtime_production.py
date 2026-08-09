"""Production dispatch for active Sector/Relationship and bound L3/L4 queries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from mosaic.dataflows.bound_runtime_query_plans import (
    build_bound_runtime_query_plan,
)
from mosaic.dataflows.frozen_adaptive_queries import FrozenAdaptiveQueryStore
from mosaic.scorecard.l3_l4_preservation import (
    L3_TOOL_ROSTER,
    build_l3_l4_preservation_overlay,
)


_ACTIVE_BOUND_STAGES = {
    *((agent_id, agent_id) for agent_id in L3_TOOL_ROSTER),
    ("alpha_discovery", "alpha_discovery"),
    ("cro", "cro"),
    ("autonomous_execution", "autonomous_execution"),
    ("cio", "cio_proposal"),
    ("cio", "cio_final"),
}


class BoundRuntimeAdaptiveQueryPreparer:
    """Compile a validated bound snapshot into one frozen L3/L4 query bundle."""

    def __init__(
        self,
        *,
        root: str | Path,
        frozen_store: FrozenAdaptiveQueryStore,
        materializer: Any,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.frozen_store = frozen_store
        self.materializer = materializer

    def __call__(
        self,
        *,
        agent_id: str,
        stage: str,
        as_of: str,
        initial_payloads: Mapping[str, str],
        runtime_inputs: Mapping[str, Any],
        candidate_scope: Mapping[str, Any] | None,
        allowed_tools: Sequence[str],
    ) -> dict[str, Any]:
        # The validated bound snapshot is the sole authority for the query domain.
        del runtime_inputs, candidate_scope
        plan = build_bound_runtime_query_plan(
            agent_id=agent_id,
            stage=stage,
            as_of=as_of,
            initial_payloads=initial_payloads,
            allowed_tools=allowed_tools,
        )
        return self.frozen_store.prepare(
            agent_id=agent_id,
            stage=stage,
            preservation_stage=plan["preservation_stage"],
            as_of=as_of,
            authorized_scope=plan["authorized_scope"],
            initial_query_requests=plan["initial_query_requests"],
            query_requests=plan["query_requests"],
            preservation_overlay=build_l3_l4_preservation_overlay(self.root),
            materializer=self.materializer,
        )


class ActiveAdaptiveQueryPreparer:
    """Dispatch the active Agent/stage to its already-established query compiler."""

    def __init__(
        self,
        *,
        sector_relationship_preparer: Any,
        bound_runtime_preparer: Any,
    ) -> None:
        self.sector_relationship_preparer = sector_relationship_preparer
        self.bound_runtime_preparer = bound_runtime_preparer

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        agent_id = kwargs.get("agent_id")
        stage = kwargs.get("stage")
        preparer = (
            self.bound_runtime_preparer
            if (agent_id, stage) in _ACTIVE_BOUND_STAGES
            else self.sector_relationship_preparer
        )
        result = preparer(**kwargs)
        if not isinstance(result, dict):
            raise ValueError("adaptive query preparer returned a non-object result")
        return result


__all__ = [
    "ActiveAdaptiveQueryPreparer",
    "BoundRuntimeAdaptiveQueryPreparer",
]
