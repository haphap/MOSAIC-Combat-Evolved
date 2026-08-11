"""Compile role-bound runtime snapshots from accepted in-run outputs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from mosaic.scorecard.accepted_output_contracts import (
    validate_accepted_output_record_schema,
)
from mosaic.scorecard.canonical_json import canonical_hash

from .exceptions import DataVendorUnavailable
from .runtime_paths import agent_cache_root, isolated_agent_runtime_path


_SUPERINVESTORS = frozenset({"ackman", "burry", "druckenmiller", "munger"})
_MACRO_AGENTS = frozenset(
    {
        "central_bank",
        "china",
        "commodities",
        "eu_economy",
        "euro_area_financial_conditions",
        "geopolitical",
        "institutional_flow",
        "market_breadth",
        "us_economy",
        "us_financial_conditions",
    }
)
_SECTOR_AGENTS = frozenset(
    {
        "agriculture",
        "biotech",
        "consumer",
        "energy",
        "financials",
        "industrials",
        "real_estate_construction",
        "relationship_mapper",
        "semiconductor",
        "technology",
    }
)
_STAGE_BY_KIND = {
    "MACRO_TRANSMISSION": None,
    "STANDARD_SECTOR_SELECTION": None,
    "RELATIONSHIP_GRAPH": "relationship_mapper",
    "SUPERINVESTOR_SELECTION": None,
    "ALPHA_DISCOVERY": "alpha_discovery",
    "CIO_PROPOSAL": "cio_proposal",
    "CRO_RISK_REVIEW": "cro",
    "EXECUTION_ASSESSMENT": "autonomous_execution",
    "CIO_FINAL": "cio_final",
}


def runtime_snapshot_root() -> Path:
    isolated = isolated_agent_runtime_path("runtime_snapshots")
    if isolated is not None:
        return isolated
    explicit = os.getenv("MOSAIC_RUNTIME_SNAPSHOT_DIR")
    if explicit:
        return Path(explicit).expanduser()
    return agent_cache_root() / "runtime_snapshots"


def bound_runtime_snapshot_relative_path(
    *,
    agent_id: str,
    stage: str,
    tool_id: str,
    as_of: str,
    graph_run_id: str,
) -> Path:
    """Return the immutable graph-bound location used by producer and loader."""
    date.fromisoformat(as_of)
    graph_hash = canonical_hash(graph_run_id).removeprefix("sha256:")
    return Path(as_of) / f"{agent_id}.{stage}.{tool_id}.{graph_hash}.json"


def render_bound_runtime_snapshot(snapshot: Mapping[str, Any]) -> str:
    """Render a bound snapshot exactly as the read-only tool materializer returns it."""
    return json.dumps(
        dict(snapshot),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def bound_runtime_snapshot_output_hash(snapshot: Mapping[str, Any]) -> str:
    rendered = render_bound_runtime_snapshot(snapshot)
    return "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def publish_bound_runtime_snapshot(
    snapshot: Mapping[str, Any],
    *,
    tool_id: str,
    output_root: Path,
) -> dict[str, Any]:
    """Atomically publish one immutable graph-bound snapshot."""
    relative_path = bound_runtime_snapshot_relative_path(
        agent_id=_required_text(snapshot.get("agent_id"), "agent_id"),
        stage=_required_text(snapshot.get("stage"), "stage"),
        tool_id=tool_id,
        as_of=_as_of_date(snapshot.get("as_of"), "as_of"),
        graph_run_id=_required_text(snapshot.get("graph_run_id"), "graph_run_id"),
    )
    path = output_root / relative_path
    rendered = render_bound_runtime_snapshot(snapshot)
    output_hash = "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        if path.read_text(encoding="utf-8") != rendered:
            raise DataVendorUnavailable("immutable bound runtime snapshot collision")
        return {
            "cache_status": "HIT",
            "output_path": relative_path.as_posix(),
            "output_hash": output_hash,
        }

    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, path)
            cache_status = "MISS"
        except FileExistsError:
            if path.read_text(encoding="utf-8") != rendered:
                raise DataVendorUnavailable("immutable bound runtime snapshot collision")
            cache_status = "HIT"
    finally:
        temporary_path.unlink(missing_ok=True)
    return {
        "cache_status": cache_status,
        "output_path": relative_path.as_posix(),
        "output_hash": output_hash,
    }


def _required_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DataVendorUnavailable(f"{field} must be an object")
    return value


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DataVendorUnavailable(f"{field} must be a non-empty string")
    return value.strip()


def _parse_timestamp(value: Any, field: str) -> datetime:
    text = _required_text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataVendorUnavailable(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DataVendorUnavailable(f"{field} must include a timezone")
    return parsed


def _as_of_date(value: Any, field: str) -> str:
    text = _required_text(value, field)
    try:
        if "T" in text:
            return _parse_timestamp(text, field).date().isoformat()
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise DataVendorUnavailable(f"{field} must contain an ISO-8601 date") from exc


def _accepted_stage(*, agent_id: str, accepted_kind: str) -> str:
    fixed = _STAGE_BY_KIND.get(accepted_kind)
    if fixed is not None:
        return fixed
    if accepted_kind == "MACRO_TRANSMISSION" and agent_id in _MACRO_AGENTS:
        return agent_id
    if accepted_kind == "STANDARD_SECTOR_SELECTION" and agent_id in _SECTOR_AGENTS:
        return agent_id
    if accepted_kind == "SUPERINVESTOR_SELECTION" and agent_id in _SUPERINVESTORS:
        return agent_id
    raise DataVendorUnavailable(
        f"accepted output lineage is invalid: {agent_id}/{accepted_kind}"
    )


def _validate_accepted_records(
    *,
    accepted_output_refs: Sequence[Mapping[str, Any]],
    accepted_output_records: Sequence[Mapping[str, Any]],
    graph_run_id: str,
    as_of: str,
) -> list[tuple[Mapping[str, Any], dict[str, Any], dict[str, Any]]]:
    records_by_id: dict[str, Mapping[str, Any]] = {}
    for record in accepted_output_records:
        accepted_id = _required_text(record.get("accepted_output_id"), "accepted_output_id")
        if accepted_id in records_by_id:
            raise DataVendorUnavailable("accepted output records contain duplicate IDs")
        records_by_id[accepted_id] = record
    if len(records_by_id) != len(accepted_output_refs):
        raise DataVendorUnavailable("accepted output refs/records do not form an exact set")

    validated: list[tuple[Mapping[str, Any], dict[str, Any], dict[str, Any]]] = []
    seen_ids: set[str] = set()
    for raw_ref in accepted_output_refs:
        if set(raw_ref) != {
            "accepted_output_kind",
            "agent_id",
            "accepted_output_id",
            "accepted_output_hash",
        }:
            raise DataVendorUnavailable("accepted output ref fields mismatch")
        accepted_id = _required_text(raw_ref.get("accepted_output_id"), "accepted_output_id")
        if accepted_id in seen_ids:
            raise DataVendorUnavailable("accepted output refs contain duplicate IDs")
        seen_ids.add(accepted_id)
        record = records_by_id.get(accepted_id)
        if record is None:
            raise DataVendorUnavailable("accepted output ref has no exact record")
        agent_id = _required_text(record.get("agent_id"), "record.agent_id")
        accepted_kind = _required_text(
            record.get("accepted_output_kind"), "record.accepted_output_kind"
        )
        try:
            validate_accepted_output_record_schema(
                record,
                agent_id=agent_id,
                accepted_kind=accepted_kind,
                allow_runtime_authority="runtime_opportunity_authority" in record,
                require_runtime_audit="runtime_audit" in record,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DataVendorUnavailable(
                f"accepted output record contract is invalid: {accepted_id}"
            ) from exc
        expected_hash = canonical_hash(
            {key: value for key, value in record.items() if key != "accepted_output_hash"}
        )
        expected_ref = {
            "accepted_output_kind": accepted_kind,
            "agent_id": agent_id,
            "accepted_output_id": accepted_id,
            "accepted_output_hash": expected_hash,
        }
        if dict(raw_ref) != expected_ref or record.get("accepted_output_hash") != expected_hash:
            raise DataVendorUnavailable("accepted output record hash/ref mismatch")
        if record.get("graph_run_id") != graph_run_id or _as_of_date(
            record.get("as_of"), "record.as_of"
        ) != as_of:
            raise DataVendorUnavailable("accepted output record run/as_of mismatch")
        evidence_id = "accepted-evidence:" + expected_hash.removeprefix("sha256:")
        projected_ref = {
            **expected_ref,
            "stage": _accepted_stage(agent_id=agent_id, accepted_kind=accepted_kind),
            "as_of": as_of,
            "evidence_ids": [evidence_id],
        }
        evidence = {
            "evidence_id": evidence_id,
            "source_kind": "ACCEPTED_OUTPUT",
            "source_id": accepted_id,
            "metric": "accepted_output_kind",
            "value": accepted_kind,
            "unit": "state",
            "as_of": as_of,
            "available_at": _required_text(record.get("accepted_at"), "record.accepted_at"),
            "source_fingerprint": expected_hash,
        }
        validated.append((record, projected_ref, evidence))
    return sorted(validated, key=lambda row: row[1]["accepted_output_id"])


def _validate_current_positions(
    runtime_state: Mapping[str, Any], *, as_of: str, generated_at: str
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    captured_at = _required_text(runtime_state.get("captured_at"), "captured_at")
    if _parse_timestamp(captured_at, "captured_at") > _parse_timestamp(
        generated_at, "generated_at"
    ):
        raise DataVendorUnavailable("runtime state was captured after snapshot generation")
    positions = _required_mapping(runtime_state.get("current_positions"), "current_positions")
    required = {
        "snapshot_status",
        "position_source",
        "source_error_code",
        "position_snapshot_hash",
        "positions",
    }
    if set(positions) != required:
        raise DataVendorUnavailable("current positions fields mismatch")
    status = positions.get("snapshot_status")
    if status not in {"loaded", "empty_confirmed", "missing"}:
        raise DataVendorUnavailable("current positions status is invalid")
    position_rows = positions.get("positions")
    if not isinstance(position_rows, list):
        raise DataVendorUnavailable("current positions must be an array")
    if status == "missing" and position_rows:
        raise DataVendorUnavailable("missing position snapshot cannot contain positions")
    snapshot_hash = _required_text(
        positions.get("position_snapshot_hash"), "position_snapshot_hash"
    )
    if not snapshot_hash.startswith("sha256:") or len(snapshot_hash) != 71:
        raise DataVendorUnavailable("position snapshot hash is invalid")
    evidence = {
        "evidence_id": "position-authority",
        "source_kind": "POSITION_SNAPSHOT",
        "source_id": "position-snapshot:" + snapshot_hash.removeprefix("sha256:"),
        "metric": "snapshot_status",
        "value": status,
        "unit": "state",
        "as_of": as_of,
        "available_at": captured_at,
        "source_fingerprint": snapshot_hash,
    }
    return positions, evidence


def _validate_decision_policy(
    runtime_state: Mapping[str, Any], *, as_of: str
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    release = _required_mapping(
        runtime_state.get("decision_policy_release"), "decision_policy_release"
    )
    if set(release) != {
        "schema_version",
        "policy_release_id",
        "effective_at",
        "owner_revisions",
        "policies",
        "release_hash",
    } or release.get("schema_version") != "deterministic_decision_policy_release_v1":
        raise DataVendorUnavailable("decision policy release fields mismatch")
    release_body = {
        key: value for key, value in release.items() if key != "release_hash"
    }
    identity_body = {
        key: value for key, value in release_body.items() if key != "policy_release_id"
    }
    expected_id = "decision-policy:" + canonical_hash(identity_body).removeprefix(
        "sha256:"
    )
    if (
        release.get("policy_release_id") != expected_id
        or release.get("release_hash") != canonical_hash(release_body)
    ):
        raise DataVendorUnavailable("decision policy release hash mismatch")
    effective_at = _required_text(release.get("effective_at"), "policy.effective_at")
    if _parse_timestamp(effective_at, "policy.effective_at").date() > date.fromisoformat(
        as_of
    ):
        raise DataVendorUnavailable("decision policy release is not effective for as_of")
    policies = _required_mapping(release.get("policies"), "policy.policies")
    cro = _required_mapping(policies.get("cro"), "policy.policies.cro")
    max_single = cro.get("max_single_name_weight")
    max_sector = cro.get("max_sector_weight")
    if not isinstance(max_single, (int, float)) or not isinstance(
        max_sector, (int, float)
    ):
        raise DataVendorUnavailable("decision policy weights are invalid")
    evidence = {
        "evidence_id": "decision-policy-authority",
        "source_kind": "POLICY_CONSTRAINT",
        "source_id": release["policy_release_id"],
        "metric": "max_single_name_weight",
        "value": float(max_single),
        "unit": "portfolio_weight",
        "as_of": as_of,
        "available_at": effective_at,
        "source_fingerprint": release["release_hash"],
    }
    return release, evidence


def _previous_target_binding(
    runtime_state: Mapping[str, Any], *, as_of: str
) -> tuple[str | None, str | None]:
    previous = _required_mapping(
        runtime_state.get("previous_target_state"), "previous_target_state"
    )
    if set(previous) != {
        "schema_version",
        "snapshot_status",
        "final_target_hash",
        "as_of_date",
        "portfolio_actions",
        "source_error_code",
    } or previous.get("schema_version") != "portfolio.previous_target_state.v1":
        raise DataVendorUnavailable("previous target state fields mismatch")
    status = previous.get("snapshot_status")
    final_hash = previous.get("final_target_hash")
    previous_as_of = previous.get("as_of_date")
    actions = previous.get("portfolio_actions")
    if status not in {"loaded", "empty_confirmed", "missing"} or not isinstance(
        actions, list
    ):
        raise DataVendorUnavailable("previous target state is invalid")
    if status == "loaded":
        if (
            not isinstance(final_hash, str)
            or not final_hash.startswith("sha256:")
            or not isinstance(previous_as_of, str)
            or date.fromisoformat(previous_as_of) >= date.fromisoformat(as_of)
        ):
            raise DataVendorUnavailable("loaded previous target binding is invalid")
        return (
            "previous-target:" + final_hash.removeprefix("sha256:"),
            final_hash,
        )
    if final_hash is not None or previous_as_of is not None or actions:
        raise DataVendorUnavailable("empty previous target binding is inconsistent")
    return None, None


def _cio_proposal_candidates(
    rows: Sequence[tuple[Mapping[str, Any], dict[str, Any], dict[str, Any]]],
    *,
    current_positions: Mapping[str, Any],
    position_evidence_id: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    current_weights: dict[str, float] = {}
    for raw_position in current_positions["positions"]:
        position = _required_mapping(raw_position, "current position")
        ts_code = _required_text(position.get("ticker"), "current position ticker")
        weight = position.get("current_weight")
        if not isinstance(weight, (int, float)):
            raise DataVendorUnavailable("current position weight is invalid")
        current_weights[ts_code] = float(weight)
        candidates.append(
            {
                "candidate_ref": "current-position:" + ts_code,
                "ts_code": ts_code,
                "source_kind": "CURRENT_POSITION",
                "current_weight": float(weight),
                "reference_target_weight": None,
                "source_output_id": None,
                "source_output_hash": None,
                "metrics": {"current_weight": float(weight)},
                "evidence_ids": [position_evidence_id],
            }
        )
    source_specs = {
        "STANDARD_SECTOR_SELECTION": ("SECTOR_SELECTION", "long_picks"),
        "SUPERINVESTOR_SELECTION": ("SUPERINVESTOR_SELECTION", "picks"),
        "ALPHA_DISCOVERY": ("ALPHA_DISCOVERY", "novel_picks"),
    }
    for record, ref, _evidence in rows:
        source_spec = source_specs.get(ref["accepted_output_kind"])
        if source_spec is None:
            continue
        payload = _required_mapping(record["output"], "record.output")["payload"]
        payload = _required_mapping(payload, "record.output.payload")
        selection = _required_mapping(payload["selection"], "accepted selection")
        picks = selection[source_spec[1]]
        if not isinstance(picks, list):
            raise DataVendorUnavailable("accepted selection picks must be an array")
        for pick in picks:
            pick = _required_mapping(pick, "accepted selection pick")
            ts_code = _required_text(pick.get("ts_code"), "accepted pick ts_code")
            conviction = pick.get("conviction")
            if not isinstance(conviction, (int, float)):
                raise DataVendorUnavailable("accepted pick conviction is invalid")
            candidates.append(
                {
                    "candidate_ref": "accepted-candidate:"
                    + canonical_hash(
                        {
                            "accepted_output_id": ref["accepted_output_id"],
                            "ts_code": ts_code,
                        }
                    ).removeprefix("sha256:"),
                    "ts_code": ts_code,
                    "source_kind": source_spec[0],
                    "current_weight": current_weights.get(ts_code, 0.0),
                    "reference_target_weight": float(conviction),
                    "source_output_id": ref["accepted_output_id"],
                    "source_output_hash": ref["accepted_output_hash"],
                    "metrics": {"source_conviction": float(conviction)},
                    "evidence_ids": list(ref["evidence_ids"]),
                }
            )
    ts_codes = [candidate["ts_code"] for candidate in candidates]
    if len(ts_codes) != len(set(ts_codes)):
        raise DataVendorUnavailable("CIO proposal sources contain duplicate securities")
    return sorted(candidates, key=lambda row: row["ts_code"])


def _validate_candidate_target(
    runtime_state: Mapping[str, Any],
    *,
    graph_run_id: str,
    as_of: str,
    current_positions: Mapping[str, Any],
    proposal_record: Mapping[str, Any],
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    candidate = _required_mapping(
        runtime_state.get("candidate_target_state"), "candidate_target_state"
    )
    expected_fields = {
        "schema_version",
        "run_id",
        "cohort",
        "as_of_date",
        "proposal_hash",
        "l4_run_snapshot_hash",
        "candidate_target_hash",
        "position_snapshot_hash",
        "previous_target_hash",
        "market_data_vintage_hash",
        "portfolio_actions",
        "confidence",
        "frozen",
    }
    if (
        set(candidate) != expected_fields
        or candidate.get("schema_version") != "portfolio.candidate_target_state.v1"
        or candidate.get("run_id") != graph_run_id
        or candidate.get("as_of_date") != as_of
        or candidate.get("frozen") is not True
        or candidate.get("position_snapshot_hash")
        != current_positions["position_snapshot_hash"]
    ):
        raise DataVendorUnavailable("candidate target state identity mismatch")
    hash_body = {
        key: value
        for key, value in candidate.items()
        if key not in {"schema_version", "candidate_target_hash", "frozen"}
    }
    if candidate.get("candidate_target_hash") != canonical_hash(hash_body):
        raise DataVendorUnavailable("candidate target state hash mismatch")
    proposal_payload = _required_mapping(proposal_record["output"], "proposal.output")[
        "payload"
    ]
    proposal_payload = _required_mapping(proposal_payload, "proposal.output.payload")
    if candidate.get("proposal_hash") != proposal_payload.get("proposal_hash"):
        raise DataVendorUnavailable("candidate target does not bind the CIO proposal")
    actions = candidate.get("portfolio_actions")
    if not isinstance(actions, list):
        raise DataVendorUnavailable("candidate target actions must be an array")
    decision = _required_mapping(proposal_payload.get("decision"), "proposal.decision")
    target_positions = decision.get("target_positions")
    if not isinstance(target_positions, list):
        raise DataVendorUnavailable("accepted CIO target positions must be an array")
    accepted_targets = {
        _required_text(
            _required_mapping(row, "accepted CIO target position").get("ts_code"),
            "accepted CIO target ts_code",
        ): _required_mapping(row, "accepted CIO target position").get("target_weight")
        for row in target_positions
    }
    runtime_targets = {
        _required_text(
            _required_mapping(row, "candidate target action").get("ticker"),
            "candidate target ticker",
        ): _required_mapping(row, "candidate target action").get("target_weight")
        for row in actions
    }
    if accepted_targets != runtime_targets:
        raise DataVendorUnavailable(
            "candidate target actions differ from the accepted CIO proposal"
        )
    market_hash = _required_text(
        candidate.get("market_data_vintage_hash"), "market_data_vintage_hash"
    )
    evidence = {
        "evidence_id": "candidate-market-authority",
        "source_kind": "MARKET_SNAPSHOT",
        "source_id": "market-vintage:" + market_hash.removeprefix("sha256:"),
        "metric": "candidate_count",
        "value": len(actions),
        "unit": "count",
        "as_of": as_of,
        "available_at": runtime_state["captured_at"],
        "source_fingerprint": market_hash,
    }
    return candidate, evidence


def _validate_portfolio_exposure(
    runtime_state: Mapping[str, Any], *, candidate: Mapping[str, Any], as_of: str
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    exposure = _required_mapping(
        runtime_state.get("portfolio_exposure_state"), "portfolio_exposure_state"
    )
    expected_fields = {
        "schema_version",
        "candidate_target_hash",
        "l4_run_snapshot_hash",
        "exposure_hash",
        "gross_exposure",
        "net_exposure",
        "cash_weight",
        "ticker_weights",
        "sector_weights",
        "frozen",
    }
    if (
        set(exposure) != expected_fields
        or exposure.get("schema_version") != "portfolio.exposure_state.v1"
        or exposure.get("frozen") is not True
        or exposure.get("candidate_target_hash")
        != candidate["candidate_target_hash"]
        or exposure.get("l4_run_snapshot_hash") != candidate["l4_run_snapshot_hash"]
    ):
        raise DataVendorUnavailable("portfolio exposure state identity mismatch")
    hash_body = {
        key: value
        for key, value in exposure.items()
        if key not in {"schema_version", "exposure_hash", "frozen"}
    }
    if exposure.get("exposure_hash") != canonical_hash(hash_body):
        raise DataVendorUnavailable("portfolio exposure state hash mismatch")
    evidence = {
        "evidence_id": "portfolio-exposure-authority",
        "source_kind": "DERIVED_METRIC",
        "source_id": "portfolio-exposure:"
        + exposure["exposure_hash"].removeprefix("sha256:"),
        "metric": "gross_exposure",
        "value": exposure["gross_exposure"],
        "unit": "portfolio_weight",
        "as_of": as_of,
        "available_at": runtime_state["captured_at"],
        "source_fingerprint": exposure["exposure_hash"],
    }
    return exposure, evidence


def _cro_candidates(
    candidate: Mapping[str, Any],
    *,
    current_positions: Mapping[str, Any],
    evidence_ids: list[str],
) -> list[dict[str, Any]]:
    current_weights = {
        _required_text(
            _required_mapping(row, "current position").get("ticker"),
            "current position ticker",
        ): float(_required_mapping(row, "current position")["current_weight"])
        for row in current_positions["positions"]
    }
    rows = []
    for raw_action in candidate["portfolio_actions"]:
        action = _required_mapping(raw_action, "candidate target action")
        ts_code = _required_text(action.get("ticker"), "candidate target ticker")
        target = action.get("target_weight")
        if not isinstance(target, (int, float)):
            raise DataVendorUnavailable("candidate target weight is invalid")
        current = float(action.get("current_weight", current_weights.get(ts_code, 0.0)))
        rows.append(
            {
                "candidate_ref": "cro-candidate:"
                + canonical_hash(
                    {
                        "candidate_target_hash": candidate["candidate_target_hash"],
                        "ts_code": ts_code,
                    }
                ).removeprefix("sha256:"),
                "ts_code": ts_code,
                "proposal_position_ref": "proposal-position:"
                + canonical_hash(
                    {
                        "proposal_hash": candidate["proposal_hash"],
                        "ts_code": ts_code,
                    }
                ).removeprefix("sha256:"),
                "current_weight": current,
                "proposed_target_weight": float(target),
                "proposed_delta_weight": float(target) - current,
                "sector_id": action.get("sector") or "unclassified",
                "metrics": {"target_weight": float(target)},
                "evidence_ids": evidence_ids,
            }
        )
    return sorted(rows, key=lambda row: row["ts_code"])


def _validate_cro_review_state(
    runtime_state: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
    cro_record: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    review = _required_mapping(runtime_state.get("cro_review_state"), "cro_review_state")
    expected_fields = {
        "schema_version",
        "run_id",
        "candidate_target_hash",
        "l4_run_snapshot_hash",
        "source_status",
        "stage_skip_id",
        "stage_skip_hash",
        "review_hash",
        "output",
        "frozen",
    }
    if (
        set(review) != expected_fields
        or review.get("schema_version") != "decision.cro_review_state.v1"
        or review.get("frozen") is not True
        or review.get("candidate_target_hash")
        != candidate["candidate_target_hash"]
        or review.get("l4_run_snapshot_hash") != candidate["l4_run_snapshot_hash"]
    ):
        raise DataVendorUnavailable("CRO review state identity mismatch")
    hash_body = {
        key: value
        for key, value in review.items()
        if key not in {"schema_version", "review_hash", "frozen"}
    }
    if review.get("review_hash") != canonical_hash(hash_body):
        raise DataVendorUnavailable("CRO review state hash mismatch")
    if review.get("source_status") == "ACCEPTED_OUTPUT":
        if (
            cro_record is None
            or review.get("stage_skip_id") is not None
            or review.get("stage_skip_hash") is not None
        ):
            raise DataVendorUnavailable("accepted CRO review control is incomplete")
        accepted_payload = _required_mapping(cro_record["output"], "cro.output")[
            "payload"
        ]
        accepted_payload = _required_mapping(accepted_payload, "cro.output.payload")
        if accepted_payload.get("frozen_proposal_hash") != candidate["proposal_hash"]:
            raise DataVendorUnavailable("CRO accepted output binds another proposal")
    elif review.get("source_status") == "NO_EVALUATION_OBJECT":
        if (
            cro_record is not None
            or not isinstance(review.get("stage_skip_id"), str)
            or not isinstance(review.get("stage_skip_hash"), str)
            or candidate["portfolio_actions"]
        ):
            raise DataVendorUnavailable("CRO stage skip control is invalid")
    else:
        raise DataVendorUnavailable("CRO review source status is invalid")
    return review


def _control_source(
    *,
    agent_id: str,
    accepted_kind: str,
    state: Mapping[str, Any],
    ref: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if state["source_status"] == "ACCEPTED_OUTPUT":
        if ref is None:
            raise DataVendorUnavailable("accepted runtime control has no accepted ref")
        return {
            "source_status": "ACCEPTED_OUTPUT",
            "agent_id": agent_id,
            "accepted_output_kind": accepted_kind,
            "accepted_output_id": ref["accepted_output_id"],
            "accepted_output_hash": ref["accepted_output_hash"],
            "stage_skip_id": None,
            "stage_skip_hash": None,
        }
    return {
        "source_status": "NO_EVALUATION_OBJECT",
        "agent_id": agent_id,
        "accepted_output_kind": accepted_kind,
        "accepted_output_id": None,
        "accepted_output_hash": None,
        "stage_skip_id": state["stage_skip_id"],
        "stage_skip_hash": state["stage_skip_hash"],
    }


def _liquidity_vintage(
    statuses: Any, *, tickers: Sequence[str], as_of: str
) -> str:
    if not isinstance(statuses, list):
        raise DataVendorUnavailable("resolved source statuses must be an array")
    scopes = []
    for ticker in sorted(set(tickers)):
        scope = f"ticker:{ticker}"
        matches = [
            row
            for row in statuses
            if isinstance(row, Mapping)
            and row.get("source_id") == "execution_liquidity_state"
            and row.get("scope") == scope
        ]
        if len(matches) > 1:
            raise DataVendorUnavailable("liquidity source status is duplicated")
        status = matches[0] if matches else None
        scopes.append(
            {
                "source_id": "execution_liquidity_state",
                "scope": scope,
                "status": status.get("status") if status else "missing",
                "as_of": status.get("as_of") if status else None,
                "snapshot_hash": status.get("snapshot_hash") if status else None,
                "error_code": (
                    status.get("error_code")
                    if status
                    else "execution_liquidity_state_adapter_not_resolved"
                ),
                "adapter_id": status.get("adapter_id") if status else None,
            }
        )
    return canonical_hash(
        {
            "source_id": "execution_liquidity_state",
            "as_of_date": as_of,
            "scopes": scopes,
        }
    )


def _execution_candidates(
    candidate: Mapping[str, Any], *, evidence_ids: list[str]
) -> list[dict[str, Any]]:
    rows = []
    for raw_action in candidate["portfolio_actions"]:
        action = _required_mapping(raw_action, "candidate target action")
        ts_code = _required_text(action.get("ticker"), "candidate target ticker")
        target = action.get("target_weight")
        current = action.get("current_weight", 0.0)
        if not isinstance(target, (int, float)) or not isinstance(
            current, (int, float)
        ):
            raise DataVendorUnavailable("execution candidate weight is invalid")
        delta = float(target) - float(current)
        rows.append(
            {
                "candidate_ref": "execution-candidate:"
                + canonical_hash(
                    {
                        "candidate_target_hash": candidate["candidate_target_hash"],
                        "ts_code": ts_code,
                    }
                ).removeprefix("sha256:"),
                "ts_code": ts_code,
                "order_intent_ref": "order-intent:"
                + canonical_hash(
                    {
                        "candidate_target_hash": candidate["candidate_target_hash"],
                        "ts_code": ts_code,
                        "delta_weight": delta,
                    }
                ).removeprefix("sha256:"),
                "current_weight": float(current),
                "target_weight": float(target),
                "requested_delta_weight": delta,
                "side": "BUY" if delta > 1e-9 else "SELL" if delta < -1e-9 else "HOLD",
                "metrics": {"absolute_delta_weight": abs(delta)},
                "evidence_ids": evidence_ids,
            }
        )
    return sorted(rows, key=lambda row: row["ts_code"])


def _validate_execution_state(
    runtime_state: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
    cro_state: Mapping[str, Any],
    execution_record: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    execution = _required_mapping(
        runtime_state.get("execution_feasibility_state"),
        "execution_feasibility_state",
    )
    expected_fields = {
        "schema_version",
        "run_id",
        "candidate_target_hash",
        "l4_run_snapshot_hash",
        "cro_review_hash",
        "source_status",
        "stage_skip_id",
        "stage_skip_hash",
        "liquidity_vintage_hash",
        "feasibility_hash",
        "output",
        "frozen",
    }
    if (
        set(execution) != expected_fields
        or execution.get("schema_version")
        != "decision.execution_feasibility_state.v1"
        or execution.get("frozen") is not True
        or execution.get("candidate_target_hash")
        != candidate["candidate_target_hash"]
        or execution.get("l4_run_snapshot_hash")
        != candidate["l4_run_snapshot_hash"]
        or execution.get("cro_review_hash") != cro_state["review_hash"]
    ):
        raise DataVendorUnavailable("execution feasibility state identity mismatch")
    hash_body = {
        key: value
        for key, value in execution.items()
        if key not in {"schema_version", "feasibility_hash", "frozen"}
    }
    if execution.get("feasibility_hash") != canonical_hash(hash_body):
        raise DataVendorUnavailable("execution feasibility state hash mismatch")
    if execution.get("source_status") == "ACCEPTED_OUTPUT":
        if (
            execution_record is None
            or execution.get("stage_skip_id") is not None
            or execution.get("stage_skip_hash") is not None
        ):
            raise DataVendorUnavailable("accepted execution control is incomplete")
        accepted_payload = _required_mapping(
            execution_record["output"], "execution.output"
        )["payload"]
        accepted_payload = _required_mapping(
            accepted_payload, "execution.output.payload"
        )
        if accepted_payload.get("frozen_proposal_hash") != candidate["proposal_hash"]:
            raise DataVendorUnavailable("execution accepted output binds another proposal")
    elif execution.get("source_status") == "NO_EVALUATION_OBJECT":
        if (
            execution_record is not None
            or not isinstance(execution.get("stage_skip_id"), str)
            or not isinstance(execution.get("stage_skip_hash"), str)
            or candidate["portfolio_actions"]
        ):
            raise DataVendorUnavailable("execution stage skip control is invalid")
    else:
        raise DataVendorUnavailable("execution source status is invalid")
    return execution


def _cio_final_candidates(
    candidate: Mapping[str, Any], *, evidence_ids: list[str]
) -> list[dict[str, Any]]:
    rows = []
    for raw_action in candidate["portfolio_actions"]:
        action = _required_mapping(raw_action, "candidate target action")
        ts_code = _required_text(action.get("ticker"), "candidate target ticker")
        target = action.get("target_weight")
        current = action.get("current_weight", 0.0)
        if not isinstance(target, (int, float)) or not isinstance(
            current, (int, float)
        ):
            raise DataVendorUnavailable("CIO final candidate weight is invalid")
        rows.append(
            {
                "candidate_ref": "cio-final-candidate:"
                + canonical_hash(
                    {
                        "candidate_target_hash": candidate["candidate_target_hash"],
                        "ts_code": ts_code,
                    }
                ).removeprefix("sha256:"),
                "ts_code": ts_code,
                "proposal_position_ref": "proposal-position:"
                + canonical_hash(
                    {
                        "proposal_hash": candidate["proposal_hash"],
                        "ts_code": ts_code,
                    }
                ).removeprefix("sha256:"),
                "current_weight": float(current),
                "proposed_target_weight": float(target),
                "proposed_delta_weight": float(target) - float(current),
                "metrics": {"target_weight": float(target)},
                "evidence_ids": evidence_ids,
            }
        )
    return sorted(rows, key=lambda row: row["ts_code"])


def _superinvestor_candidates(
    rows: Sequence[tuple[Mapping[str, Any], dict[str, Any], dict[str, Any]]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for record, ref, _evidence in rows:
        if ref["accepted_output_kind"] != "STANDARD_SECTOR_SELECTION":
            continue
        payload = _required_mapping(record["output"], "record.output")["payload"]
        selection = _required_mapping(payload, "record.output.payload")["selection"]
        selection = _required_mapping(selection, "record.output.payload.selection")
        directions = (
            ("PREFERRED", "preferred_direction", "long_picks"),
            ("LEAST_PREFERRED", "least_preferred_direction", "short_or_avoid_picks"),
        )
        for direction, direction_field, picks_field in directions:
            direction_row = _required_mapping(selection[direction_field], direction_field)
            picks = selection[picks_field]
            if not isinstance(picks, list):
                raise DataVendorUnavailable(f"{picks_field} must be an array")
            for pick in picks:
                pick = _required_mapping(pick, picks_field)
                candidate_identity = {
                    "accepted_output_id": ref["accepted_output_id"],
                    "pick_local_id": pick["pick_local_id"],
                }
                candidates.append(
                    {
                        "candidate_ref": "runtime-candidate:"
                        + canonical_hash(candidate_identity).removeprefix("sha256:"),
                        "ts_code": pick["ts_code"],
                        "source_output_id": ref["accepted_output_id"],
                        "source_output_hash": ref["accepted_output_hash"],
                        "source_sector_agent_id": ref["agent_id"],
                        "source_direction_id": direction_row["direction_id"],
                        "source_direction": direction,
                        "metrics": {"conviction": pick["conviction"]},
                        "evidence_ids": list(ref["evidence_ids"]),
                    }
                )
    return sorted(candidates, key=lambda row: (row["ts_code"], row["candidate_ref"]))


def _alpha_candidates(
    rows: Sequence[tuple[Mapping[str, Any], dict[str, Any], dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[str]]:
    selected_ts_codes: set[str] = set()
    observed_superinvestors: set[str] = set()
    for record, ref, _evidence in rows:
        if ref["accepted_output_kind"] != "SUPERINVESTOR_SELECTION":
            continue
        observed_superinvestors.add(ref["agent_id"])
        payload = _required_mapping(record["output"], "record.output")["payload"]
        selection = _required_mapping(payload, "record.output.payload")["selection"]
        selection = _required_mapping(selection, "record.output.payload.selection")
        picks = selection["picks"]
        if not isinstance(picks, list):
            raise DataVendorUnavailable("Superinvestor picks must be an array")
        for pick in picks:
            selected_ts_codes.add(
                _required_text(
                    _required_mapping(pick, "Superinvestor pick").get("ts_code"),
                    "Superinvestor pick ts_code",
                )
            )
    if observed_superinvestors != _SUPERINVESTORS:
        raise DataVendorUnavailable(
            "Alpha snapshot requires all Superinvestor accepted outputs"
        )
    candidates = []
    for source in _superinvestor_candidates(rows):
        if source["ts_code"] in selected_ts_codes:
            continue
        candidates.append(
            {
                "candidate_ref": source["candidate_ref"],
                "ts_code": source["ts_code"],
                "source_output_id": source["source_output_id"],
                "source_output_hash": source["source_output_hash"],
                "source_agent_id": source["source_sector_agent_id"],
                "source_candidate_ref": source["candidate_ref"],
                "omitted_by_superinvestor_agents": sorted(_SUPERINVESTORS),
                "metrics": source["metrics"],
                "evidence_ids": source["evidence_ids"],
            }
        )
    return candidates, sorted(selected_ts_codes)


def _seal_snapshot(
    *,
    contract_version: str,
    graph_run_id: str,
    agent_id: str,
    stage: str,
    as_of: str,
    generated_at: str,
    candidates: list[dict[str, Any]],
    constraints: dict[str, Any],
    role_context: dict[str, Any],
    refs: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate_body = {
        "candidate_status": "AVAILABLE" if candidates else "EMPTY_CONFIRMED",
        "candidate_universe": candidates,
    }
    candidate_hash = canonical_hash(candidate_body)
    candidate_id = "candidate-universe:" + candidate_hash.removeprefix("sha256:")
    constraint_hash = canonical_hash(constraints)
    constraint_id = "constraint-set:" + constraint_hash.removeprefix("sha256:")
    candidate_scope = {
        "candidate_universe_id": candidate_id,
        "candidate_universe_hash": candidate_hash,
        "constraint_set_id": constraint_id,
        "constraint_set_hash": constraint_hash,
    }
    body = {
        "schema_version": contract_version,
        "contract_version": contract_version,
        "snapshot_id": "runtime-snapshot:pending",
        "graph_run_id": graph_run_id,
        "agent_id": agent_id,
        "stage": stage,
        "as_of": as_of,
        "generated_at": generated_at,
        "pit_status": "VERIFIED",
        "candidate_scope": candidate_scope,
        "candidate_scope_hash": canonical_hash(candidate_scope),
        "candidate_universe_id": candidate_id,
        "candidate_universe_hash": candidate_hash,
        **candidate_body,
        "constraint_set_id": constraint_id,
        "constraint_set_hash": constraint_hash,
        "constraints": constraints,
        "role_context": role_context,
        "role_context_hash": canonical_hash(role_context),
        "upstream_accepted_output_refs": refs,
        "evidence_ledger": evidence,
    }
    snapshot_id = "runtime-snapshot:" + canonical_hash(body).removeprefix("sha256:")
    body["snapshot_id"] = snapshot_id
    return {**body, "snapshot_hash": canonical_hash(body)}


def compile_bound_runtime_snapshot(
    *,
    agent_id: str,
    stage: str,
    as_of: str,
    graph_run_id: str,
    accepted_output_refs: Sequence[Mapping[str, Any]],
    accepted_output_records: Sequence[Mapping[str, Any]],
    runtime_state: Mapping[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    """Compile one strict role snapshot from exact accepted records and runtime state."""
    supported = (agent_id in _SUPERINVESTORS and stage == agent_id) or (
        agent_id == "alpha_discovery" and stage == "alpha_discovery"
    ) or (agent_id == "cio" and stage in {"cio_proposal", "cio_final"}) or (
        agent_id == "cro" and stage == "cro"
    ) or (
        agent_id == "autonomous_execution" and stage == "autonomous_execution"
    )
    if not supported:
        raise DataVendorUnavailable(
            f"bound runtime compiler does not support {agent_id}/{stage} yet"
        )
    _parse_timestamp(generated_at, "generated_at")
    validated = _validate_accepted_records(
        accepted_output_refs=accepted_output_refs,
        accepted_output_records=accepted_output_records,
        graph_run_id=graph_run_id,
        as_of=as_of,
    )
    if agent_id == "alpha_discovery":
        allowed_kinds = {
            "STANDARD_SECTOR_SELECTION",
            "RELATIONSHIP_GRAPH",
            "SUPERINVESTOR_SELECTION",
        }
    elif agent_id == "cio" and stage == "cio_proposal":
        allowed_kinds = {
            "MACRO_TRANSMISSION",
            "STANDARD_SECTOR_SELECTION",
            "RELATIONSHIP_GRAPH",
            "SUPERINVESTOR_SELECTION",
            "ALPHA_DISCOVERY",
        }
    elif agent_id == "cio":
        allowed_kinds = {
            "CIO_PROPOSAL",
            "CRO_RISK_REVIEW",
            "EXECUTION_ASSESSMENT",
        }
    elif agent_id == "cro":
        allowed_kinds = {"CIO_PROPOSAL"}
    elif agent_id == "autonomous_execution":
        allowed_kinds = {"CIO_PROPOSAL", "CRO_RISK_REVIEW"}
    else:
        allowed_kinds = {
            "MACRO_TRANSMISSION",
            "STANDARD_SECTOR_SELECTION",
            "RELATIONSHIP_GRAPH",
        }
    if not validated or any(row[1]["accepted_output_kind"] not in allowed_kinds for row in validated):
        raise DataVendorUnavailable("Superinvestor accepted-output scope is invalid")
    expected_runtime_fields = {"captured_at", "current_positions"}
    if agent_id == "cio" and stage == "cio_proposal":
        expected_runtime_fields.update(
            {"previous_target_state", "decision_policy_release"}
        )
    elif agent_id == "cio":
        expected_runtime_fields.update(
            {
                "decision_policy_release",
                "candidate_target_state",
                "cro_review_state",
                "execution_feasibility_state",
            }
        )
    elif agent_id == "cro":
        expected_runtime_fields.update(
            {
                "decision_policy_release",
                "candidate_target_state",
                "portfolio_exposure_state",
            }
        )
    elif agent_id == "autonomous_execution":
        expected_runtime_fields.update(
            {
                "decision_policy_release",
                "candidate_target_state",
                "cro_review_state",
                "resolved_source_statuses",
                "execution_mode",
            }
        )
    if set(runtime_state) != expected_runtime_fields:
        raise DataVendorUnavailable("bound runtime state fields mismatch")
    current_positions, position_evidence = _validate_current_positions(
        runtime_state, as_of=as_of, generated_at=generated_at
    )
    accepted_evidence_ids = [row[2]["evidence_id"] for row in validated]
    if agent_id == "cio" and stage == "cio_final":
        proposal_rows = [
            row
            for row in validated
            if row[1]["accepted_output_kind"] == "CIO_PROPOSAL"
        ]
        cro_rows = [
            row
            for row in validated
            if row[1]["accepted_output_kind"] == "CRO_RISK_REVIEW"
        ]
        execution_rows = [
            row
            for row in validated
            if row[1]["accepted_output_kind"] == "EXECUTION_ASSESSMENT"
        ]
        if (
            len(proposal_rows) != 1
            or len(cro_rows) > 1
            or len(execution_rows) > 1
        ):
            raise DataVendorUnavailable("CIO final accepted control scope is invalid")
        proposal_record, proposal_ref, proposal_evidence = proposal_rows[0]
        cro_record = cro_rows[0][0] if cro_rows else None
        cro_ref = cro_rows[0][1] if cro_rows else None
        execution_record = execution_rows[0][0] if execution_rows else None
        execution_ref = execution_rows[0][1] if execution_rows else None
        candidate, _market_evidence = _validate_candidate_target(
            runtime_state,
            graph_run_id=graph_run_id,
            as_of=as_of,
            current_positions=current_positions,
            proposal_record=proposal_record,
        )
        cro_state = _validate_cro_review_state(
            runtime_state, candidate=candidate, cro_record=cro_record
        )
        execution_state = _validate_execution_state(
            runtime_state,
            candidate=candidate,
            cro_state=cro_state,
            execution_record=execution_record,
        )
        cro_control = _control_source(
            agent_id="cro",
            accepted_kind="CRO_RISK_REVIEW",
            state=cro_state,
            ref=cro_ref,
        )
        execution_control = _control_source(
            agent_id="autonomous_execution",
            accepted_kind="EXECUTION_ASSESSMENT",
            state=execution_state,
            ref=execution_ref,
        )
        liquidity_hash = _required_text(
            execution_state["liquidity_vintage_hash"], "liquidity_vintage_hash"
        )
        liquidity_evidence = {
            "evidence_id": "execution-liquidity-authority",
            "source_kind": "MARKET_SNAPSHOT",
            "source_id": "liquidity-vintage:"
            + liquidity_hash.removeprefix("sha256:"),
            "metric": "scoped_ticker_count",
            "value": len(candidate["portfolio_actions"]),
            "unit": "count",
            "as_of": as_of,
            "available_at": runtime_state["captured_at"],
            "source_fingerprint": liquidity_hash,
        }
        release, policy_evidence = _validate_decision_policy(runtime_state, as_of=as_of)
        cro_policy = _required_mapping(
            _required_mapping(release["policies"], "policy.policies")["cro"],
            "policy.policies.cro",
        )
        candidate_evidence_ids = [
            proposal_evidence["evidence_id"],
            liquidity_evidence["evidence_id"],
        ]
        if cro_rows:
            candidate_evidence_ids.append(cro_rows[0][2]["evidence_id"])
        if execution_rows:
            candidate_evidence_ids.append(execution_rows[0][2]["evidence_id"])
        candidates = _cio_final_candidates(
            candidate, evidence_ids=candidate_evidence_ids
        )
        constraints = {
            "max_total_target_weight": 1.0,
            "min_cash_weight": 0.0,
            "max_single_name_weight": float(cro_policy["max_single_name_weight"]),
            "restricted_ts_codes": [],
            "evidence_ids": [policy_evidence["evidence_id"]],
        }
        role_context = {
            "context_kind": "CIO_PORTFOLIO_DECISION",
            "decision_stage": "FINAL",
            "proposal_accepted_output_id": proposal_ref["accepted_output_id"],
            "proposal_accepted_output_hash": proposal_ref["accepted_output_hash"],
            "cro_control_source": cro_control,
            "execution_control_source": execution_control,
            "evidence_ids": [
                position_evidence["evidence_id"],
                liquidity_evidence["evidence_id"],
            ],
        }
        return _seal_snapshot(
            contract_version="cio_decision_snapshot_v1",
            graph_run_id=graph_run_id,
            agent_id=agent_id,
            stage=stage,
            as_of=as_of,
            generated_at=generated_at,
            candidates=candidates,
            constraints=constraints,
            role_context=role_context,
            refs=[row[1] for row in validated],
            evidence=[
                *[row[2] for row in validated],
                position_evidence,
                liquidity_evidence,
                policy_evidence,
            ],
        )
    if agent_id == "autonomous_execution":
        proposal_rows = [
            row
            for row in validated
            if row[1]["accepted_output_kind"] == "CIO_PROPOSAL"
        ]
        cro_rows = [
            row
            for row in validated
            if row[1]["accepted_output_kind"] == "CRO_RISK_REVIEW"
        ]
        if len(proposal_rows) != 1 or len(cro_rows) > 1:
            raise DataVendorUnavailable("Execution accepted control scope is invalid")
        proposal_record, proposal_ref, proposal_evidence = proposal_rows[0]
        cro_record = cro_rows[0][0] if cro_rows else None
        cro_ref = cro_rows[0][1] if cro_rows else None
        candidate, _market_evidence = _validate_candidate_target(
            runtime_state,
            graph_run_id=graph_run_id,
            as_of=as_of,
            current_positions=current_positions,
            proposal_record=proposal_record,
        )
        cro_state = _validate_cro_review_state(
            runtime_state, candidate=candidate, cro_record=cro_record
        )
        control_source = _control_source(
            agent_id="cro",
            accepted_kind="CRO_RISK_REVIEW",
            state=cro_state,
            ref=cro_ref,
        )
        tickers = [
            _required_text(
                _required_mapping(action, "candidate target action").get("ticker"),
                "candidate target ticker",
            )
            for action in candidate["portfolio_actions"]
        ]
        liquidity_hash = _liquidity_vintage(
            runtime_state["resolved_source_statuses"], tickers=tickers, as_of=as_of
        )
        liquidity_evidence = {
            "evidence_id": "execution-liquidity-authority",
            "source_kind": "MARKET_SNAPSHOT",
            "source_id": "liquidity-vintage:"
            + liquidity_hash.removeprefix("sha256:"),
            "metric": "scoped_ticker_count",
            "value": len(tickers),
            "unit": "count",
            "as_of": as_of,
            "available_at": runtime_state["captured_at"],
            "source_fingerprint": liquidity_hash,
        }
        release, policy_evidence = _validate_decision_policy(runtime_state, as_of=as_of)
        execution_policy = _required_mapping(
            _required_mapping(release["policies"], "policy.policies")[
                "autonomous_execution"
            ],
            "policy.policies.autonomous_execution",
        )
        execution_mode = runtime_state["execution_mode"]
        if execution_mode not in {"PAPER", "REAL"}:
            raise DataVendorUnavailable("execution mode is invalid")
        candidate_evidence_ids = [
            proposal_evidence["evidence_id"],
            liquidity_evidence["evidence_id"],
        ]
        if cro_rows:
            candidate_evidence_ids.append(cro_rows[0][2]["evidence_id"])
        candidates = _execution_candidates(
            candidate, evidence_ids=candidate_evidence_ids
        )
        constraints = {
            "execution_mode": execution_mode,
            "max_slippage_bps": float(execution_policy["slippage_cap"]) * 10_000,
            "max_participation_rate": 1.0,
            "min_trade_weight": float(execution_policy["min_delta_trade_weight"]),
            "max_slice_count": 100,
            "prohibited_ts_codes": [],
            "evidence_ids": [policy_evidence["evidence_id"]],
        }
        order_intent_hash = canonical_hash(candidates)
        role_context = {
            "context_kind": "EXECUTION_ORDER_FEASIBILITY",
            "proposal_accepted_output_id": proposal_ref["accepted_output_id"],
            "proposal_accepted_output_hash": proposal_ref["accepted_output_hash"],
            "cro_control_source": control_source,
            "order_intent_set_id": "order-intent-set:"
            + order_intent_hash.removeprefix("sha256:"),
            "order_intent_set_hash": order_intent_hash,
            "liquidity_vintage_hash": liquidity_hash,
            "evidence_ids": [
                position_evidence["evidence_id"],
                liquidity_evidence["evidence_id"],
            ],
        }
        return _seal_snapshot(
            contract_version="execution_snapshot_v1",
            graph_run_id=graph_run_id,
            agent_id=agent_id,
            stage=stage,
            as_of=as_of,
            generated_at=generated_at,
            candidates=candidates,
            constraints=constraints,
            role_context=role_context,
            refs=[row[1] for row in validated],
            evidence=[
                *[row[2] for row in validated],
                position_evidence,
                liquidity_evidence,
                policy_evidence,
            ],
        )
    if agent_id == "cro":
        proposal_rows = [
            row
            for row in validated
            if row[1]["accepted_output_kind"] == "CIO_PROPOSAL"
        ]
        if len(proposal_rows) != 1:
            raise DataVendorUnavailable("CRO snapshot requires one CIO proposal record")
        proposal_record, proposal_ref, proposal_evidence = proposal_rows[0]
        candidate, market_evidence = _validate_candidate_target(
            runtime_state,
            graph_run_id=graph_run_id,
            as_of=as_of,
            current_positions=current_positions,
            proposal_record=proposal_record,
        )
        exposure, exposure_evidence = _validate_portfolio_exposure(
            runtime_state, candidate=candidate, as_of=as_of
        )
        release, policy_evidence = _validate_decision_policy(runtime_state, as_of=as_of)
        cro_policy = _required_mapping(
            _required_mapping(release["policies"], "policy.policies")["cro"],
            "policy.policies.cro",
        )
        candidates = _cro_candidates(
            candidate,
            current_positions=current_positions,
            evidence_ids=[
                proposal_evidence["evidence_id"],
                market_evidence["evidence_id"],
            ],
        )
        constraints = {
            "max_total_target_weight": 1.0,
            "max_single_name_weight": float(cro_policy["max_single_name_weight"]),
            "max_sector_weight": float(cro_policy["max_sector_weight"]),
            "restricted_ts_codes": [],
            "evidence_ids": [policy_evidence["evidence_id"]],
        }
        role_context = {
            "context_kind": "CRO_PROPOSAL_RISK_REVIEW",
            "proposal_accepted_output_id": proposal_ref["accepted_output_id"],
            "proposal_accepted_output_hash": proposal_ref["accepted_output_hash"],
            "position_snapshot_id": position_evidence["source_id"],
            "position_snapshot_hash": position_evidence["source_fingerprint"],
            "portfolio_exposure_snapshot_id": exposure_evidence["source_id"],
            "portfolio_exposure_snapshot_hash": exposure["exposure_hash"],
            "evidence_ids": [
                position_evidence["evidence_id"],
                exposure_evidence["evidence_id"],
                market_evidence["evidence_id"],
            ],
        }
        return _seal_snapshot(
            contract_version="cro_risk_snapshot_v1",
            graph_run_id=graph_run_id,
            agent_id=agent_id,
            stage=stage,
            as_of=as_of,
            generated_at=generated_at,
            candidates=candidates,
            constraints=constraints,
            role_context=role_context,
            refs=[proposal_ref],
            evidence=[
                proposal_evidence,
                position_evidence,
                market_evidence,
                exposure_evidence,
                policy_evidence,
            ],
        )
    if agent_id == "cio":
        release, policy_evidence = _validate_decision_policy(runtime_state, as_of=as_of)
        previous_target_id, previous_target_hash = _previous_target_binding(
            runtime_state, as_of=as_of
        )
        candidates = _cio_proposal_candidates(
            validated,
            current_positions=current_positions,
            position_evidence_id=position_evidence["evidence_id"],
        )
        cro_policy = _required_mapping(
            _required_mapping(release["policies"], "policy.policies")["cro"],
            "policy.policies.cro",
        )
        constraints = {
            "max_total_target_weight": 1.0,
            "min_cash_weight": 0.0,
            "max_single_name_weight": float(cro_policy["max_single_name_weight"]),
            "restricted_ts_codes": [],
            "evidence_ids": [policy_evidence["evidence_id"]],
        }
        role_context = {
            "context_kind": "CIO_PORTFOLIO_DECISION",
            "decision_stage": "PROPOSAL",
            "position_snapshot_id": position_evidence["source_id"],
            "position_snapshot_hash": position_evidence["source_fingerprint"],
            "previous_target_id": previous_target_id,
            "previous_target_hash": previous_target_hash,
            "evidence_ids": [
                *accepted_evidence_ids,
                position_evidence["evidence_id"],
            ],
        }
        return _seal_snapshot(
            contract_version="cio_decision_snapshot_v1",
            graph_run_id=graph_run_id,
            agent_id=agent_id,
            stage=stage,
            as_of=as_of,
            generated_at=generated_at,
            candidates=candidates,
            constraints=constraints,
            role_context=role_context,
            refs=[row[1] for row in validated],
            evidence=[
                *[row[2] for row in validated],
                position_evidence,
                policy_evidence,
            ],
        )
    if agent_id == "alpha_discovery":
        candidates, excluded_ts_codes = _alpha_candidates(validated)
    else:
        candidates = _superinvestor_candidates(validated)
        excluded_ts_codes = []
    if current_positions["snapshot_status"] == "missing" and candidates:
        raise DataVendorUnavailable(
            "Superinvestor candidates require an available position snapshot"
        )
    if agent_id == "alpha_discovery":
        constraints = {
            "cash_only": current_positions["snapshot_status"] == "missing",
            "allow_new_positions": current_positions["snapshot_status"] != "missing",
            "max_novel_pick_count": 10,
            "excluded_selected_ts_codes": excluded_ts_codes,
            "evidence_ids": [position_evidence["evidence_id"]],
        }
    else:
        constraints = {
            "cash_only": current_positions["snapshot_status"] == "missing",
            "allow_new_positions": current_positions["snapshot_status"] != "missing",
            "max_pick_count": 10,
            "max_total_conviction": 1.0,
            "prohibited_ts_codes": [],
            "evidence_ids": [position_evidence["evidence_id"]],
        }
    origin_hash = canonical_hash(candidates)
    if agent_id == "alpha_discovery":
        selected_hash = canonical_hash(excluded_ts_codes)
        role_context = {
            "context_kind": "ALPHA_NOVELTY_SEARCH",
            "superinvestor_selection_set_id": "super-selection-set:"
            + selected_hash.removeprefix("sha256:"),
            "superinvestor_selection_set_hash": selected_hash,
            "excluded_security_set_id": "excluded-security-set:"
            + selected_hash.removeprefix("sha256:"),
            "excluded_security_set_hash": selected_hash,
            "evidence_ids": accepted_evidence_ids,
        }
        contract_version = "alpha_candidate_snapshot_v1"
    else:
        role_context = {
            "context_kind": "SUPERINVESTOR_CANDIDATE_SELECTION",
            "candidate_origin_set_id": "candidate-origin-set:"
            + origin_hash.removeprefix("sha256:"),
            "candidate_origin_set_hash": origin_hash,
            "evidence_ids": accepted_evidence_ids,
        }
        contract_version = "superinvestor_candidate_snapshot_v1"
    return _seal_snapshot(
        contract_version=contract_version,
        graph_run_id=graph_run_id,
        agent_id=agent_id,
        stage=stage,
        as_of=as_of,
        generated_at=generated_at,
        candidates=candidates,
        constraints=constraints,
        role_context=role_context,
        refs=[row[1] for row in validated],
        evidence=[*[row[2] for row in validated], position_evidence],
    )


__all__ = [
    "bound_runtime_snapshot_output_hash",
    "bound_runtime_snapshot_relative_path",
    "compile_bound_runtime_snapshot",
    "publish_bound_runtime_snapshot",
    "render_bound_runtime_snapshot",
    "runtime_snapshot_root",
]
