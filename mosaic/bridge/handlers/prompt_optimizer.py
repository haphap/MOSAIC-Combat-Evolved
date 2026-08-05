"""Minimal JSON-RPC persistence for Prompt optimizer experiments."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from ..protocol import INTERNAL_ERROR, INVALID_PARAMS, RpcError
from ..registry import method
from mosaic.scorecard.prompt_optimizer_store import PromptOptimizerStore


_STORE: PromptOptimizerStore | None = None


def _store() -> PromptOptimizerStore:
    global _STORE
    from mosaic.scorecard import get_store

    db_path = get_store().db_path
    if _STORE is None or _STORE.db_path != db_path:
        _STORE = PromptOptimizerStore(db_path)
    return _STORE


def _record(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"record"}:
        raise RpcError(INVALID_PARAMS, "expected only 'record'")
    value = params.get("record")
    if not isinstance(value, dict):
        raise RpcError(INVALID_PARAMS, "'record' must be an object")
    return value


def _id(params: dict[str, Any], key: str) -> str:
    if set(params) != {key}:
        raise RpcError(INVALID_PARAMS, f"expected only '{key}'")
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a non-empty string")
    return value.strip()


def _write(
    params: dict[str, Any],
    action: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    try:
        return action(_record(params))
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"prompt optimizer persistence failed: {exc}") from exc


def _release_summary(candidate_id: str | None) -> dict[str, str] | None:
    root = os.environ.get("MOSAIC_ACTIVE_PROMPT_RELEASE_REGISTRY_ROOT", "").strip()
    if not root or not candidate_id:
        return None
    matches: list[dict[str, Any]] = []
    for path in (Path(root) / "releases").glob("*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if value.get("release_evidence", {}).get("candidate_id") == candidate_id:
            matches.append(value)
    if not matches:
        return None
    latest = max(matches, key=lambda value: (str(value.get("created_at", "")), str(value.get("release_id", ""))))
    return {
        "release_id": str(latest.get("release_id", "")),
        "lifecycle_state": str(latest.get("lifecycle_state", "")),
    }


@method("prompt_optimizer.put_candidate")
def put_candidate(params: dict[str, Any]) -> dict[str, Any]:
    return _write(params, _store().put_candidate)


@method("prompt_optimizer.get_candidate")
def get_candidate(params: dict[str, Any]) -> dict[str, Any]:
    return {"record": _store().get_candidate(_id(params, "candidate_id"))}


@method("prompt_optimizer.put_split")
def put_split(params: dict[str, Any]) -> dict[str, Any]:
    return _write(params, _store().put_split)


@method("prompt_optimizer.get_split")
def get_split(params: dict[str, Any]) -> dict[str, Any]:
    return {"record": _store().get_split(_id(params, "split_id"))}


@method("prompt_optimizer.put_family")
def put_family(params: dict[str, Any]) -> dict[str, Any]:
    return _write(params, _store().put_family)


@method("prompt_optimizer.get_family")
def get_family(params: dict[str, Any]) -> dict[str, Any]:
    return {"record": _store().get_family(_id(params, "family_id"))}


@method("prompt_optimizer.put_experiment")
def put_experiment(params: dict[str, Any]) -> dict[str, Any]:
    if not {"record"}.issubset(params) or not set(params).issubset(
        {"record", "promotion_policy"}
    ):
        raise RpcError(INVALID_PARAMS, "expected record and optional promotion_policy")
    record = params.get("record")
    policy = params.get("promotion_policy")
    if not isinstance(record, dict) or (policy is not None and not isinstance(policy, dict)):
        raise RpcError(INVALID_PARAMS, "invalid experiment persistence parameters")
    try:
        return _store().put_experiment(record, policy)
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(
            INTERNAL_ERROR, f"prompt optimizer persistence failed: {exc}"
        ) from exc


@method("prompt_optimizer.get_experiment")
def get_experiment(params: dict[str, Any]) -> dict[str, Any]:
    return {"record": _store().get_experiment(_id(params, "experiment_id"))}


@method("prompt_optimizer.list_experiments")
def list_experiments(params: dict[str, Any]) -> dict[str, Any]:
    return {"records": _store().list_experiments(_id(params, "family_id"))}


@method("prompt_optimizer.put_run")
def put_run(params: dict[str, Any]) -> dict[str, Any]:
    return _write(params, _store().put_run)


@method("prompt_optimizer.claim_run")
def claim_run(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"record", "lease_duration_ms"}:
        raise RpcError(INVALID_PARAMS, "expected record and lease_duration_ms")
    record = params.get("record")
    duration = params.get("lease_duration_ms")
    if not isinstance(record, dict) or isinstance(duration, bool) or not isinstance(duration, int):
        raise RpcError(INVALID_PARAMS, "invalid run claim parameters")
    try:
        return {"record": _store().claim_run(record, duration)}
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"prompt optimizer persistence failed: {exc}") from exc


@method("prompt_optimizer.list_runs")
def list_runs(params: dict[str, Any]) -> dict[str, Any]:
    return {"records": _store().list_runs(_id(params, "experiment_id"))}


@method("prompt_optimizer.latest_summary")
def latest_summary(params: dict[str, Any]) -> dict[str, Any]:
    summary = _store().latest_summary(_id(params, "cohort"))
    candidate = summary["candidate"]
    summary["release"] = _release_summary(
        None if candidate is None else str(candidate["candidateId"])
    )
    return summary


@method("prompt_optimizer.training_projection")
def training_projection(params: dict[str, Any]) -> dict[str, Any]:
    required = {"agent_id", "stage", "cohort", "cutoff_at"}
    optional = {"excluded_sample_ids"}
    if not required.issubset(params) or not set(params).issubset(required | optional):
        raise RpcError(
            INVALID_PARAMS,
            "expected agent_id, stage, cohort, cutoff_at and optional excluded_sample_ids",
        )
    values: dict[str, str] = {}
    for key in sorted(required):
        value = params.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RpcError(INVALID_PARAMS, f"'{key}' must be a non-empty string")
        values[key] = value.strip()
    excluded = params.get("excluded_sample_ids", [])
    if not isinstance(excluded, list) or any(
        not isinstance(value, str) or not value.strip() for value in excluded
    ):
        raise RpcError(INVALID_PARAMS, "'excluded_sample_ids' must be a string array")
    try:
        from mosaic.scorecard import get_store

        return {
            "projection": get_store().build_prompt_training_projection(
                **values,
                excluded_sample_ids=[value.strip() for value in excluded],
            )
        }
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"Prompt training projection failed: {exc}") from exc
