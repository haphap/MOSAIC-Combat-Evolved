"""Production adapter from trusted initial snapshots to frozen L2 query bundles."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from mosaic.dataflows.frozen_adaptive_queries import FrozenAdaptiveQueryStore
from mosaic.dataflows.sector_relationship_query_plans import (
    build_sector_relationship_query_plan,
)
from mosaic.scorecard.sector_relationship_preservation import (
    build_sector_relationship_preservation_overlay,
)


class SectorRelationshipAdaptiveQueryPreparer:
    """Compile exact L1 snapshot scope and materialize the finite L2 domain."""

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
        # L2 scope authority is the validated L1 snapshot. Runtime/candidate inputs are
        # deliberately ignored here because they are model/upstream supplied.
        del runtime_inputs, candidate_scope
        plan = build_sector_relationship_query_plan(
            agent_id=agent_id,
            stage=stage,
            as_of=as_of,
            initial_payloads=initial_payloads,
            allowed_tools=allowed_tools,
        )
        return self.frozen_store.prepare(
            agent_id=agent_id,
            stage=stage,
            as_of=as_of,
            authorized_scope=plan["authorized_scope"],
            query_requests=plan["query_requests"],
            preservation_overlay=build_sector_relationship_preservation_overlay(
                self.root
            ),
            materializer=self.materializer,
        )


__all__ = ["SectorRelationshipAdaptiveQueryPreparer"]
