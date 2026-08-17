"""``data.*`` JSON-RPC handlers — qlib-data incremental update (Request #2).

Wraps ``mosaic.dataflows.qlib_ingest`` so the TS front-end can refresh the
local qlib datasets (cn_data / cn_etf) without dropping to a raw
``python -m mosaic.dataflows.qlib_ingest`` invocation.

Surface:
    * data.incremental(kind, end[, timeout]) → append latest trading days
    * data.validate(kind[, gap_threshold]) → quality report + skip manifest
    * data.source_preflight(as_of, all_agents=true) → 26-source admission
    * data.earliest_ready_date(all_agents=true) → earliest replay-ready session
    * data.materialize_cycle_dry_run(as_of, all_agents=true) → read-only cycle plan
    * data.cycle_open(...) → source-admitted append-only cycle OPEN
    * data.cycle_commit(state) → atomic COMMITTED event + final publication
    * data.cycle_abort(run_id, reason) → append-only terminal ABORTED
    * data.source_status(as_of, route_id) → sealed capture status
    * data.snapshot_status(as_of, agent_id, stage) → frozen build status
    * data.materialize_dry_run(as_of, agent_id, stage) → read-only plan

The actual fetch runs the vendored collector in a child process and needs the
``ingest`` (+ ``data`` + ``backtest``) extras installed; absent deps surface as
DATA_ERROR rather than crashing the bridge.
"""

from __future__ import annotations

import os
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mosaic.dataflows.agent_materialization import (
    load_agent_data_route_manifest,
    open_agent_data_materialization_ledger,
)
from mosaic.dataflows.agent_cycle_authority import (
    abort_agent_cycle,
    commit_agent_cycle,
    open_agent_cycle,
)
from mosaic.dataflows.route_eligibility import (
    earliest_agent_source_ready_date,
    evaluate_agent_source_admission,
    evaluate_route_eligibility,
)
from mosaic.dataflows.runtime_paths import agent_cache_root, agent_runtime_root_override
from mosaic.bridge.tool_capabilities import get_capability_store
from mosaic.scorecard.capability_preservation import (
    load_active_capability_fixed_point,
)

from ..protocol import DATA_ERROR, INVALID_PARAMS, RpcError
from ..registry import method

_KINDS = ("stock", "etf")


def _evaluation_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_kind(params: dict[str, Any]) -> str:
    kind = params.get("kind", "stock")
    if kind not in _KINDS:
        raise RpcError(INVALID_PARAMS, f"'kind' must be one of {_KINDS}, got {kind!r}")
    return kind


def _require_str(params: dict[str, Any], key: str) -> str:
    val = params.get(key)
    if not isinstance(val, str) or not val.strip():
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a non-empty string")
    return val.strip()


def _configured_cycle_mode(*, expected: str | None = None) -> str:
    mode = os.getenv("MOSAIC_ENSURE_SNAPSHOT_MODE")
    if mode not in {"shadow", "enforce"}:
        raise RpcError(
            DATA_ERROR,
            "P1_ENSURE_MODE_DRIFT: cycle authority requires explicit "
            "MOSAIC_ENSURE_SNAPSHOT_MODE=shadow or enforce",
        )
    if expected is not None and mode != expected:
        raise RpcError(
            DATA_ERROR,
            "P1_ENSURE_MODE_DRIFT: "
            f"cycle authority mode {expected!r} does not match configured mode {mode!r}",
        )
    return mode


def _cycle_runtime_scope(mode: str):
    if mode != "shadow":
        return nullcontext()
    configured = os.getenv("MOSAIC_ENSURE_SNAPSHOT_SHADOW_ROOT")
    shadow_root = (
        Path(configured).expanduser()
        if configured
        else agent_cache_root() / "agent_materialization_shadow"
    )
    return agent_runtime_root_override(shadow_root)


def _require_date(params: dict[str, Any], key: str = "as_of") -> str:
    value = _require_str(params, key)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, f"'{key}' must be an ISO date (YYYY-MM-DD)") from exc
    if parsed.isoformat() != value:
        raise RpcError(INVALID_PARAMS, f"'{key}' must be an ISO date (YYYY-MM-DD)")
    return value


def _require_route_id(params: dict[str, Any]) -> str:
    route_id = _require_str(params, "route_id")
    known_routes = {
        route["route_id"] for route in load_agent_data_route_manifest()["routes"]
    }
    if route_id not in known_routes:
        raise RpcError(INVALID_PARAMS, f"unknown Agent data route: {route_id}")
    return route_id


def _require_sha256(params: dict[str, Any], key: str) -> str:
    value = _require_str(params, key)
    digest = value.removeprefix("sha256:")
    if (
        not value.startswith("sha256:")
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a sha256 identifier")
    return value


@method("data.incremental")
def data_incremental(params: dict[str, Any]) -> dict[str, Any]:
    """Append the latest trading days to an existing qlib dataset.

    Params:
        kind: "stock" (cn_data) | "etf" (cn_etf), default "stock"
        end:  str (YYYY-MM-DD) — fetch through this date
        timeout: int seconds — **per-Tushare-request** cap passed to the
                 collector's ``--timeout`` (NOT a wall-clock cap on the whole
                 ingest), default 120.

    Returns ``{kind, returncode, qlib_dir, ok}``.

    Temp/working data (raw + normalized CSVs) is written to
    ``~/.cache/mosaic_tushare_{raw,norm}`` — out of the repo, so the vendored
    collectors never pollute the project tree.

    Blocking note: this runs the vendored collector subprocess **synchronously**
    and a real incremental update can take minutes; the bridge processes it on
    its request loop, so concurrent RPCs wait until it returns. Run ingest as a
    cron / one-off rather than alongside latency-sensitive calls.
    """
    kind = _require_kind(params)
    end = _require_str(params, "end")
    timeout = params.get("timeout", 120)
    if not isinstance(timeout, int) or timeout < 1:
        raise RpcError(INVALID_PARAMS, "'timeout' must be a positive integer")

    try:
        from mosaic.dataflows.qlib_ingest import CollectorNotFound, ingest_incremental
    except ImportError as exc:
        raise RpcError(DATA_ERROR, f"qlib_ingest unavailable: {exc}") from exc

    try:
        outcome = ingest_incremental(
            end=end, kind=kind, timeout=timeout, stream_stdout=False
        )
    except CollectorNotFound as exc:
        raise RpcError(DATA_ERROR, str(exc)) from exc
    except FileNotFoundError as exc:
        raise RpcError(DATA_ERROR, str(exc)) from exc
    except Exception as exc:
        raise RpcError(DATA_ERROR, f"{type(exc).__name__}: {exc}") from exc

    return {
        "kind": kind,
        "returncode": outcome.returncode,
        "qlib_dir": str(outcome.qlib_dir) if outcome.qlib_dir else None,
        "ok": outcome.returncode == 0,
    }


@method("data.validate")
def data_validate(params: dict[str, Any]) -> dict[str, Any]:
    """Validate an ingested qlib dataset + (re)write the skip manifest.

    Params:
        kind: "stock" | "etf", default "stock"
        gap_threshold: float (optional, default 0.01)

    Returns the validation summary dict from ``validate_after_ingest``.
    """
    kind = _require_kind(params)
    gap_threshold = params.get("gap_threshold", 0.01)
    if not isinstance(gap_threshold, (int, float)) or isinstance(gap_threshold, bool):
        raise RpcError(INVALID_PARAMS, "'gap_threshold' must be numeric")

    try:
        from mosaic.dataflows.qlib_ingest import (
            DEFAULT_QLIB_DATA_DIR,
            DEFAULT_QLIB_ETF_DATA_DIR,
            validate_after_ingest,
        )
    except ImportError as exc:
        raise RpcError(DATA_ERROR, f"qlib_ingest unavailable: {exc}") from exc

    qlib_dir = DEFAULT_QLIB_ETF_DATA_DIR if kind == "etf" else DEFAULT_QLIB_DATA_DIR
    try:
        return validate_after_ingest(qlib_dir=qlib_dir, gap_threshold=float(gap_threshold))
    except FileNotFoundError as exc:
        raise RpcError(DATA_ERROR, str(exc)) from exc
    except Exception as exc:
        raise RpcError(DATA_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("data.source_status")
def data_source_status(params: dict[str, Any]) -> dict[str, Any]:
    """Return the sealed capture status for one logical Agent data route."""
    as_of = _require_date(params)
    route_id = _require_route_id(params)
    try:
        return open_agent_data_materialization_ledger(create=False).source_status(
            as_of=as_of,
            route_id=route_id,
        )
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(DATA_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("data.source_preflight")
def data_source_preflight(params: dict[str, Any]) -> dict[str, Any]:
    """Evaluate the 26 external routes required before cycle execution."""
    if params.get("all_agents") is not True:
        raise RpcError(INVALID_PARAMS, "'all_agents' must be true")
    as_of = _require_date(params)
    mode = os.getenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "off")
    if mode not in {"off", "shadow", "enforce"}:
        raise RpcError(
            DATA_ERROR,
            "MOSAIC_ENSURE_SNAPSHOT_MODE must be one of off, shadow, enforce",
        )

    def evaluate(*, prepare: bool) -> dict[str, Any]:
        preparation = (
            get_capability_store().prepare_source_admission(as_of=as_of)
            if prepare
            else None
        )
        result = evaluate_agent_source_admission(
            ledger=open_agent_data_materialization_ledger(create=True),
            target_date=as_of,
            evaluated_at=_evaluation_timestamp(),
            require_production_license=mode == "enforce",
        )
        if preparation is not None:
            result = {**result, "source_preparation": preparation}
        return result

    try:
        if mode == "shadow":
            configured = os.getenv("MOSAIC_ENSURE_SNAPSHOT_SHADOW_ROOT")
            shadow_root = (
                Path(configured).expanduser()
                if configured
                else agent_cache_root() / "agent_materialization_shadow"
            )
            with agent_runtime_root_override(shadow_root):
                return evaluate(prepare=True)
        return evaluate(prepare=mode == "enforce")
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(DATA_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("data.source_backfill")
def data_source_backfill(params: dict[str, Any]) -> dict[str, Any]:
    """Prepare and seal one external route for every date in a closed range."""
    route_id = _require_route_id(params)
    start_text = _require_date(params, "from")
    end_text = _require_date(params, "to")
    start = date.fromisoformat(start_text)
    end = date.fromisoformat(end_text)
    if start > end:
        raise RpcError(INVALID_PARAMS, "'from' must not be after 'to'")
    route = next(
        route
        for route in load_agent_data_route_manifest()["routes"]
        if route["route_id"] == route_id
    )
    if route["pit_strategy"] == "LOCAL_RUNTIME_AUTHORITY":
        raise RpcError(INVALID_PARAMS, "source backfill does not accept runtime routes")
    mode = os.getenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "off")
    if mode not in {"shadow", "enforce"}:
        raise RpcError(
            DATA_ERROR,
            "source backfill requires MOSAIC_ENSURE_SNAPSHOT_MODE=shadow or enforce",
        )
    historical_replay = params.get("historical_replay", False)
    if not isinstance(historical_replay, bool):
        raise RpcError(INVALID_PARAMS, "'historical_replay' must be a boolean")
    if historical_replay and mode != "shadow":
        raise RpcError(INVALID_PARAMS, "historical replay backfill requires shadow mode")

    configured = os.getenv("MOSAIC_ENSURE_SNAPSHOT_SHADOW_ROOT")
    shadow_root = (
        Path(configured).expanduser()
        if configured
        else agent_cache_root() / "agent_materialization_shadow"
    )

    def run() -> dict[str, Any]:
        store = get_capability_store()
        ledger = open_agent_data_materialization_ledger(create=True)
        rows = []
        cursor = start
        while cursor <= end:
            target_date = cursor.isoformat()
            preparation = store.prepare_source_admission(
                as_of=target_date,
                route_id=route_id,
                **({"historical_replay": True} if historical_replay else {}),
            )
            evaluated_at = _evaluation_timestamp()
            receipt = evaluate_route_eligibility(
                ledger=ledger,
                route_id=route_id,
                target_date=target_date,
                evaluated_at=evaluated_at,
                require_production_license=mode == "enforce",
            )
            ledger.append_route_eligibility(receipt)
            payload = receipt.as_dict()
            rows.append(
                {
                    "target_date": target_date,
                    "status": payload["status"],
                    "blockers": payload["blockers"],
                    "eligibility_receipt_hash": receipt.receipt_hash,
                    "source_preparation": preparation,
                }
            )
            cursor += timedelta(days=1)
        return {
            "schema_version": "agent_source_backfill_v1",
            "route_id": route_id,
            "from": start_text,
            "to": end_text,
            "status": (
                "READY" if all(row["status"] == "READY" for row in rows) else "BLOCKED"
            ),
            "dates": rows,
        }

    try:
        if mode == "shadow":
            with agent_runtime_root_override(shadow_root):
                return run()
        return run()
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(DATA_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("data.earliest_ready_date")
def data_earliest_ready_date(params: dict[str, Any]) -> dict[str, Any]:
    """Return the earliest verified trading date with historical route closure."""
    if params.get("all_agents") is not True:
        raise RpcError(INVALID_PARAMS, "'all_agents' must be true")
    mode = os.getenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "off")
    if mode not in {"off", "shadow", "enforce"}:
        raise RpcError(
            DATA_ERROR,
            "MOSAIC_ENSURE_SNAPSHOT_MODE must be one of off, shadow, enforce",
        )

    def run() -> dict[str, Any]:
        return earliest_agent_source_ready_date(
            ledger=open_agent_data_materialization_ledger(create=False),
            evaluated_at=_evaluation_timestamp(),
        )

    try:
        if mode == "shadow":
            configured = os.getenv("MOSAIC_ENSURE_SNAPSHOT_SHADOW_ROOT")
            shadow_root = (
                Path(configured).expanduser()
                if configured
                else agent_cache_root() / "agent_materialization_shadow"
            )
            with agent_runtime_root_override(shadow_root):
                return run()
        return run()
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(DATA_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("data.cycle_open")
def data_cycle_open(params: dict[str, Any]) -> dict[str, Any]:
    """Open one source-admitted Agent cycle before graph execution."""
    as_of = _require_date(params)
    run_id = _require_str(params, "run_id")
    cohort = _require_str(params, "cohort")
    mode = _require_str(params, "mode")
    cycle_kind = _require_str(params, "cycle_kind")
    if mode not in {"enforce", "shadow"}:
        raise RpcError(INVALID_PARAMS, "'mode' must be enforce or shadow")
    if cycle_kind not in {"PRODUCTION", "SHADOW", "REPLAY"}:
        raise RpcError(
            INVALID_PARAMS,
            "'cycle_kind' must be PRODUCTION, SHADOW, or REPLAY",
        )
    configured_mode = _configured_cycle_mode(expected=mode)
    if cycle_kind == "PRODUCTION" and mode != "enforce":
        raise RpcError(INVALID_PARAMS, "PRODUCTION cycle requires enforce mode")
    if cycle_kind in {"SHADOW", "REPLAY"} and mode != "shadow":
        raise RpcError(INVALID_PARAMS, f"{cycle_kind} cycle requires shadow mode")
    lease_seconds = params.get("lease_seconds", 3600)
    if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool):
        raise RpcError(INVALID_PARAMS, "'lease_seconds' must be an integer")
    try:
        fixed_point = load_active_capability_fixed_point()
        with _cycle_runtime_scope(configured_mode):
            return open_agent_cycle(
                ledger=open_agent_data_materialization_ledger(create=True),
                target_date=as_of,
                run_id=run_id,
                cohort=cohort,
                mode=mode,
                cycle_kind=cycle_kind,
                execution_behavior_release_hash=fixed_point[
                    "execution_behavior_release_hash"
                ],
                knot_coverage_manifest_v2_hash=fixed_point[
                    "knot_coverage_manifest_v2_hash"
                ],
                opened_at=_evaluation_timestamp(),
                lease_seconds=lease_seconds,
            )
    except ValueError as exc:
        raise RpcError(DATA_ERROR, str(exc)) from exc


@method("data.cycle_commit")
def data_cycle_commit(params: dict[str, Any]) -> dict[str, Any]:
    """Atomically publish one fully closed Agent cycle."""
    state = params.get("state")
    if not isinstance(state, dict):
        raise RpcError(INVALID_PARAMS, "'state' must be an object")
    try:
        mode = _configured_cycle_mode()
        with _cycle_runtime_scope(mode):
            return commit_agent_cycle(
                ledger=open_agent_data_materialization_ledger(create=True),
                state=state,
                committed_at=_evaluation_timestamp(),
            )
    except ValueError as exc:
        raise RpcError(DATA_ERROR, str(exc)) from exc


@method("data.cycle_abort")
def data_cycle_abort(params: dict[str, Any]) -> dict[str, Any]:
    """Append an ABORTED terminal event for one active cycle."""
    try:
        mode = _configured_cycle_mode()
        with _cycle_runtime_scope(mode):
            return abort_agent_cycle(
                ledger=open_agent_data_materialization_ledger(create=True),
                run_id=_require_str(params, "run_id"),
                reason=_require_str(params, "reason"),
                aborted_at=_evaluation_timestamp(),
            )
    except ValueError as exc:
        raise RpcError(DATA_ERROR, str(exc)) from exc


@method("data.snapshot_status")
def data_snapshot_status(params: dict[str, Any]) -> dict[str, Any]:
    """Return frozen snapshot-build status for one Agent execution stage."""
    as_of = _require_date(params)
    agent_id = _require_str(params, "agent_id")
    stage = _require_str(params, "stage")
    try:
        return open_agent_data_materialization_ledger(create=False).snapshot_status(
            as_of=as_of,
            agent_id=agent_id,
            stage=stage,
        )
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(DATA_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("data.materialize_dry_run")
def data_materialize_dry_run(params: dict[str, Any]) -> dict[str, Any]:
    """Plan materialization without collectors, writes, builds, or capability issue."""
    if params.get("dry_run") is not True:
        raise RpcError(INVALID_PARAMS, "'dry_run' must be true")
    as_of = _require_date(params)
    agent_id = _require_str(params, "agent_id")
    stage = _require_str(params, "stage")
    try:
        return open_agent_data_materialization_ledger(create=False).materialize_dry_run(
            as_of=as_of,
            agent_id=agent_id,
            stage=stage,
        )
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(DATA_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("data.materialize_cycle_dry_run")
def data_materialize_cycle_dry_run(params: dict[str, Any]) -> dict[str, Any]:
    """Plan exact 26-stage materialization without writes or collectors."""
    if params.get("dry_run") is not True:
        raise RpcError(INVALID_PARAMS, "'dry_run' must be true")
    if params.get("all_agents") is not True:
        raise RpcError(INVALID_PARAMS, "'all_agents' must be true")
    as_of = _require_date(params)
    try:
        return open_agent_data_materialization_ledger(
            create=False
        ).materialize_cycle_dry_run(as_of=as_of)
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(DATA_ERROR, f"{type(exc).__name__}: {exc}") from exc
