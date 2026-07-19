from __future__ import annotations

import pytest

from mosaic.autoresearch.decider import decide


def test_legacy_delta_sharpe_decider_has_no_production_promotion_edge() -> None:
    class ForbiddenDependency:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"legacy decider touched forbidden dependency: {name}")

    with pytest.raises(RuntimeError, match="KNOT promotion batch"):
        decide(
            ForbiddenDependency(),
            ForbiddenDependency(),
            {"id": 1, "delta_sharpe": 1.0, "branch_name": "legacy-branch"},
        )
