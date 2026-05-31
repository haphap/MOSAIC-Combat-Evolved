"""Derive a compact, prompt-ready context summary from a MiroFish scenario set.

Phase 7M Step 1 — the persistence-readable half of the ATLAS ``get_agent_context``
pathway. Pure stdlib (operates on the JSON-serialisable scenario dicts), so it
imports without numpy and can run deps-light.

The summary mirrors what ATLAS's ``mirofish_context.py`` surfaces to agents:
regime + index move (from the base scenario), a tail-risk one-liner (from the
worst-case scenario), and a "highest conviction" direction (the scenario with the
largest |CSI300 move|). Step 2 will format this into an agent prompt section.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

_PROBE = "000300.SH"


def _csi(scenario: Mapping[str, Any]) -> float:
    fs = scenario.get("final_state") or {}
    if "csi300_return" in fs:
        return float(fs["csi300_return"])
    p = (scenario.get("price_paths") or {}).get(_PROBE) or {}
    return float(p.get("cumulative_return", 0.0))


def derive_context(scenarios: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Reduce a scenario set to a compact context summary (pure derivation).

    Step-2 note: ``hct_direction`` is None when all moves are ~0, and
    ``tail_summary`` is None when the set has no ``tail_down`` — the prompt
    formatter must degrade cleanly on both. Duplicate ``scenario_type`` entries
    keep the last (the canonical generator emits unique types).
    """
    by_type = {s.get("scenario_type"): s for s in scenarios}
    base = by_type.get("base") or (scenarios[0] if scenarios else {})
    base_fs = base.get("final_state") or {}

    # Highest-conviction direction: the scenario with the largest |CSI300 move|.
    hct_dir = None
    hct_csi = 0.0
    for s in scenarios:
        c = _csi(s)
        if abs(c) > abs(hct_csi):
            hct_csi, hct_dir = c, ("LONG" if c >= 0 else "SHORT")

    # Tail one-liner from the worst downside scenario.
    tail = by_type.get("tail_down")
    tail_summary = None
    if tail:
        tail_summary = (
            f"{tail.get('scenario_name', 'tail_down')}: CSI300 {_csi(tail) * 100:+.1f}% "
            f"(p={tail.get('probability', 0):.0%})"
        )

    return {
        "n_scenarios": len(scenarios),
        "regime": base_fs.get("regime"),
        "narrative": base_fs.get("narrative"),
        "csi300_return": round(_csi(base), 4),
        "hct_ticker": _PROBE,
        "hct_direction": hct_dir,
        "hct_csi300_return": round(hct_csi, 4),
        "tail_summary": tail_summary,
        "engine": scenarios[0].get("engine", "montecarlo") if scenarios else "montecarlo",
    }
