"""MOSAIC MiroFish forward-simulation layer (Plan §11.8, Phase 7).

Port of ATLAS ``mirofish/`` reflexivity/forward-training to MOSAIC. See
:mod:`mosaic.mirofish.scenarios` for the numpy scenario engine + scorer.
"""

from mosaic.mirofish.scenarios import (
    ASSET_PARAMS,
    DEFAULT_START_PRICES,
    SCENARIO_TYPES,
    generate_all_scenarios,
    generate_scenario,
    score_recommendation,
)

__all__ = [
    "ASSET_PARAMS",
    "DEFAULT_START_PRICES",
    "SCENARIO_TYPES",
    "generate_all_scenarios",
    "generate_scenario",
    "score_recommendation",
]
