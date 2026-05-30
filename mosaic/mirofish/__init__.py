"""MOSAIC MiroFish forward-simulation layer (Plan §11.8, Phase 7).

Port of ATLAS ``mirofish/`` reflexivity/forward-training to MOSAIC. The scenario
engine + scorer (``scenarios``) need numpy; names are lazily imported (PEP 562
``__getattr__``) so deps-light siblings like ``mosaic.mirofish.context`` import
without pulling numpy.
"""

from __future__ import annotations

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "ASSET_PARAMS": (".scenarios", "ASSET_PARAMS"),
    "DEFAULT_START_PRICES": (".scenarios", "DEFAULT_START_PRICES"),
    "SCENARIO_TYPES": (".scenarios", "SCENARIO_TYPES"),
    "generate_all_scenarios": (".scenarios", "generate_all_scenarios"),
    "generate_scenario": (".scenarios", "generate_scenario"),
    "score_recommendation": (".scenarios", "score_recommendation"),
}

__all__ = list(_LAZY_IMPORTS.keys())


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        import importlib

        module_path, attr = _LAZY_IMPORTS[name]
        value = getattr(importlib.import_module(module_path, __package__), attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
