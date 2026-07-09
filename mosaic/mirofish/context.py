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

import hashlib
import json
from collections.abc import Mapping as MappingABC
from collections.abc import Sequence as SequenceABC
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
        "scenario_count": len(scenarios),
        "horizon_days": _horizon_days(scenarios),
        "context_hash": _context_hash(scenarios),
        "generator_version": "mirofish_context_v1",
        "regime": base_fs.get("regime"),
        "narrative": base_fs.get("narrative"),
        "csi300_return": round(_csi(base), 4),
        "hct_ticker": _PROBE,
        "hct_direction": hct_dir,
        "hct_csi300_return": round(hct_csi, 4),
        "tail_summary": tail_summary,
        "position_stress": _position_stress(scenarios),
        "engine": scenarios[0].get("engine", "montecarlo") if scenarios else "montecarlo",
    }


def _horizon_days(scenarios: Sequence[Mapping[str, Any]]) -> int | None:
    horizons: list[int] = []
    for scenario in scenarios:
        num_days = scenario.get("num_days")
        if isinstance(num_days, int) and not isinstance(num_days, bool) and num_days > 0:
            horizons.append(num_days)
            continue
        paths = scenario.get("price_paths") or {}
        if not isinstance(paths, MappingABC):
            continue
        for path in paths.values():
            if not isinstance(path, MappingABC):
                continue
            prices = path.get("prices")
            if isinstance(prices, SequenceABC) and not isinstance(prices, (str, bytes)):
                horizons.append(max(len(prices) - 1, 0))
                break
    return max(horizons) if horizons else None


def _context_hash(scenarios: Sequence[Mapping[str, Any]]) -> str:
    summary: list[dict[str, Any]] = []
    for scenario in scenarios:
        paths = scenario.get("price_paths") or {}
        path_summary: dict[str, Any] = {}
        if isinstance(paths, MappingABC):
            for ticker, path in sorted(paths.items(), key=lambda item: str(item[0])):
                if isinstance(path, MappingABC):
                    path_summary[str(ticker)] = round(float(path.get("cumulative_return", 0.0)), 6)
        summary.append({
            "scenario_type": scenario.get("scenario_type"),
            "probability": scenario.get("probability"),
            "num_days": scenario.get("num_days"),
            "final_state": scenario.get("final_state") or {},
            "portfolio_context": scenario.get("portfolio_context") or {},
            "returns": path_summary,
        })
    payload = json.dumps(summary, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _position_tickers(scenarios: Sequence[Mapping[str, Any]]) -> list[str]:
    tickers: set[str] = set()
    for scenario in scenarios:
        context = scenario.get("portfolio_context") or {}
        if not isinstance(context, MappingABC):
            continue
        raw = context.get("current_position_tickers")
        if isinstance(raw, SequenceABC) and not isinstance(raw, (str, bytes)):
            tickers.update(str(item) for item in raw if isinstance(item, str) and item.strip())
    return sorted(tickers)


def _position_stress(scenarios: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ticker in _position_tickers(scenarios):
        returns: list[float] = []
        for scenario in scenarios:
            path = (scenario.get("price_paths") or {}).get(ticker)
            if isinstance(path, MappingABC):
                returns.append(float(path.get("cumulative_return", 0.0)))
        if not returns:
            continue
        tail_loss = min(returns)
        average_return = sum(returns) / len(returns)
        positive_share = sum(1 for item in returns if item >= 0) / len(returns)
        negative_share = 1 - positive_share
        if tail_loss <= -0.20:
            action = "EXIT"
            agreement = negative_share
        elif tail_loss <= -0.12:
            action = "REDUCE"
            agreement = negative_share
        elif average_return >= 0.05 and positive_share >= 0.60:
            action = "ADD"
            agreement = positive_share
        else:
            action = "HOLD"
            agreement = max(positive_share, negative_share)
        rows.append({
            "ticker": ticker,
            "tail_loss": round(tail_loss, 4),
            "scenario_agreement": round(agreement, 4),
            "suggested_action": action,
        })
    return rows
