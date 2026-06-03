"""``darwinian.*`` JSON-RPC handlers (Plan §11.3 sub-step 3D).

Surface:
    * darwinian.compute       (cohort, today) → {written: int, agents_uniform_fallback: int}
    * darwinian.get_weights   (cohort, date?) → {agent: {weight, sharpe_30, sharpe_90, quartile}}

The TS autonomous_execution agent (Phase 3F) calls darwinian.get_weights
to replace its Phase-2 stub. Operator cron (or `pnpm dev darwinian`) calls
darwinian.compute after a scorecard.score_pending pass.
"""

from __future__ import annotations

from typing import Any, Optional

from ..protocol import INTERNAL_ERROR, INVALID_PARAMS, RpcError
from ..registry import method


def _store():
    # §14 R-T4: use the cached singleton.
    from mosaic.scorecard import get_store

    return get_store()


def _config():
    try:
        from mosaic.dataflows.config import get_config

        return get_config()
    except Exception:  # noqa: BLE001
        from mosaic.default_config import DEFAULT_CONFIG

        return DEFAULT_CONFIG


def _require_str(params: dict, key: str) -> str:
    val = params.get(key)
    if not isinstance(val, str) or not val.strip():
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a non-empty string")
    return val.strip()


# ---------------------------------------------------------------------------
# darwinian.compute
# ---------------------------------------------------------------------------


@method("darwinian.compute")
def darwinian_compute(params: dict[str, Any]) -> dict[str, Any]:
    """Compute and persist Darwinian weights for every agent in the cohort.

    Params:
        cohort: str
        today:  str (YYYY-MM-DD)

    Returns:
        {"written": <int>, "agents_uniform_fallback": <int>}
    """
    cohort = _require_str(params, "cohort")
    today = _require_str(params, "today")

    try:
        from mosaic.scorecard import compute_weights
    except ImportError as exc:
        raise RpcError(INTERNAL_ERROR, f"scorecard package not importable: {exc}") from exc

    try:
        return compute_weights(_store(), cohort=cohort, today=today, config=_config())
    except RpcError:
        raise
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


# ---------------------------------------------------------------------------
# darwinian.get_weights
# ---------------------------------------------------------------------------


@method("darwinian.get_weights")
def darwinian_get_weights(params: dict[str, Any]) -> dict[str, Any]:
    """Read the latest (or specified date's) Darwinian weight table.

    Params:
        cohort: str
        date:   str (YYYY-MM-DD, optional) — when omitted returns latest
                                              row per (cohort, agent).

    Returns:
        {"weights": {<agent>: {"weight": float,
                                "sharpe_30": float | None,
                                "sharpe_90": float | None,
                                "quartile": int | None}}}

    When the table is empty (e.g. before darwinian.compute has ever run),
    returns ``{"weights": {}}`` — caller treats that as the uniform=1.0
    Phase 2 stub fallback (Plan §11.3 design decision #7).
    """
    cohort = _require_str(params, "cohort")
    date: Optional[str] = params.get("date") or None
    if date is not None and not isinstance(date, str):
        raise RpcError(INVALID_PARAMS, "'date' must be a string when provided")

    try:
        weights = _store().get_darwinian_weights(cohort=cohort, date=date)
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc

    return {"weights": weights}
