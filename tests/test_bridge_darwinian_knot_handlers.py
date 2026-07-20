"""Fail-closed wire tests for the private KNOT runtime bridge surface."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from mosaic.bridge import handlers as _handlers_pkg  # noqa: F401
from mosaic.bridge.protocol import INVALID_PARAMS, RpcError
from mosaic.bridge.registry import get_handler
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.scorecard.darwinian_updates import LIVE_SOURCE_TOOL_BY_AGENT


class _RecordingStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.sector_budget: dict[str, Any] | None = None

    def __getattr__(self, method: str):
        def record(**kwargs: Any) -> dict[str, Any]:
            self.calls.append((method, kwargs))
            if method == "resolve_scheduled_sample_context":
                return {"as_of": "2026-07-19"}
            if method == "freeze_knot_pair_input":
                return {
                    "knot_pair_id": "pair-1",
                    "knot_pair_input_hash": f"sha256:{'a' * 64}",
                    "sector_inference_budget_contract": self.sector_budget,
                }
            if method == "resolve_knot_strict_schema_binding":
                return {
                    "accepted_output_kind": "MACRO_TRANSMISSION",
                    "schema_phase": "DEFAULT",
                    "schema_id": "macro.china.output.v1",
                    "schema_hash": f"sha256:{'b' * 64}",
                    "immutable_phase_instruction_hash": f"sha256:{'c' * 64}",
                    "structured_output_schema_binding_set_hash": f"sha256:{'d' * 64}",
                }
            return {"method": method, "params": kwargs}

        return record


class _RecordingCapabilityStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.error: ValueError | None = None
        self.agent_id = "china"
        self.stage = "china"

    def classify_and_reserve_knot_regime(self, **kwargs: Any) -> dict[str, Any]:
        self._record("classify_and_reserve_knot_regime", kwargs)
        return {
            "regime_classification_receipt_id": "regime-receipt-1",
            "evaluation_regime": "normal",
            "classified_at": "2026-07-19T09:00:00+08:00",
        }

    def verify_knot_regime_classification_receipt(
        self, receipt: dict[str, Any]
    ) -> dict[str, Any]:
        return receipt

    def verify_and_reserve_knot_pair_root(self, **kwargs: Any) -> dict[str, Any]:
        self._record("verify_and_reserve_knot_pair_root", kwargs)
        return {
            "pair_root_reservation_id": "reservation-1",
            "verified_at": "2026-07-19T09:01:00+08:00",
        }

    def verify_knot_pair_root_receipt(
        self, receipt: dict[str, Any]
    ) -> dict[str, Any]:
        return receipt

    def bind_knot_private_pair(self, **kwargs: Any) -> None:
        self._record("bind_knot_private_pair", kwargs)

    def resolve_knot_pair_side_capability(self, **kwargs: Any) -> dict[str, Any]:
        self._record("resolve_knot_pair_side_capability", kwargs)
        return {
            "graph_run_id": "graph-1",
            "run_id": "run-1",
            "agent_id": self.agent_id,
            "stage": self.stage,
        }

    def mint_knot_strict_output_validation_receipt(
        self, **kwargs: Any
    ) -> dict[str, Any]:
        self._record("mint_knot_strict_output_validation_receipt", kwargs)
        return {"strict_validation_receipt_id": "strict-receipt-1"}

    def verify_knot_strict_output_validation_receipt(
        self, receipt: dict[str, Any]
    ) -> dict[str, Any]:
        return receipt

    def mint_knot_sector_inference_usage_receipt(
        self, **kwargs: Any
    ) -> dict[str, Any]:
        self._record("mint_knot_sector_inference_usage_receipt", kwargs)
        return {"usage_receipt_id": "sector-usage-receipt-1"}

    def verify_knot_sector_inference_usage_receipt(
        self, receipt: dict[str, Any]
    ) -> dict[str, Any]:
        return receipt

    def mint_knot_control_strict_output_validation_receipt(
        self, **kwargs: Any
    ) -> dict[str, Any]:
        self._record("mint_knot_control_strict_output_validation_receipt", kwargs)
        return {"strict_validation_receipt_id": "control-strict-receipt-1"}

    def verify_knot_control_strict_output_validation_receipt(
        self, receipt: dict[str, Any]
    ) -> dict[str, Any]:
        return receipt

    def _record(self, method: str, kwargs: dict[str, Any]) -> None:
        if self.error is not None:
            raise self.error
        self.calls.append((method, kwargs))


@pytest.fixture
def stores(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_RecordingStore, _RecordingCapabilityStore]:
    scorecard = _RecordingStore()
    capabilities = _RecordingCapabilityStore()
    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    monkeypatch.setattr(module, "_store", lambda: scorecard)
    monkeypatch.setattr(module, "_capability_store", lambda: capabilities)
    return scorecard, capabilities


def _dispatch(method: str, params: dict[str, Any]) -> dict[str, Any]:
    handler = get_handler(method)
    if handler is None:
        raise AssertionError(f"method '{method}' not registered")
    return handler(params)


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"score_disposition": "SCORE"}, "SCORE requires 'outcome_label_id'"),
        (
            {
                "score_disposition": "SCORE",
                "outcome_label_id": "label-1",
                "operational_opportunity_audit_id": "failure-audit-1",
            },
            "SCORE cannot carry 'operational_opportunity_audit_id'",
        ),
        (
            {
                "score_disposition": "AGENT_FAILURE",
                "outcome_label_id": "label-1",
            },
            "AGENT_FAILURE cannot carry 'outcome_label_id'",
        ),
    ],
)
def test_append_score_rejects_mixed_disposition_receipts(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
    fields: dict[str, Any],
    message: str,
) -> None:
    scorecard, _ = stores
    with pytest.raises(RpcError, match=message):
        _dispatch(
            "darwinian.knot_append_score",
            {
                "knot_pair_id": "pair-1",
                "pair_side": "CHAMPION",
                "recorded_at": "2026-07-19T09:00:00+08:00",
                **fields,
            },
        )
    assert scorecard.calls == []


@pytest.mark.parametrize(
    ("fields", "expected_outcome", "expected_failure_audit"),
    [
        (
            {"score_disposition": "SCORE", "outcome_label_id": "label-1"},
            "label-1",
            None,
        ),
        (
            {
                "score_disposition": "AGENT_FAILURE",
                "operational_opportunity_audit_id": "failure-audit-1",
            },
            None,
            "failure-audit-1",
        ),
    ],
)
def test_append_score_forwards_one_disposition_receipt(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
    fields: dict[str, Any],
    expected_outcome: str | None,
    expected_failure_audit: str | None,
) -> None:
    scorecard, _ = stores
    _dispatch(
        "darwinian.knot_append_score",
        {
            "knot_pair_id": "pair-1",
            "pair_side": "CHAMPION",
            "recorded_at": "2026-07-19T09:00:00+08:00",
            **fields,
        },
    )
    method, forwarded = scorecard.calls[-1]
    assert method == "append_knot_research_score_record"
    assert forwarded["outcome_label_id"] == expected_outcome
    assert (
        forwarded["operational_opportunity_audit_id"]
        == expected_failure_audit
    )


def test_preregister_pair_assignment_mints_authoritative_regime_receipt(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
) -> None:
    scorecard, capabilities = stores
    source_snapshot = {"schema_version": "component_calibration_regime_snapshot_v1"}
    params = {
        "knot_research_track_id": "track-1",
        "research_slot_id": "slot-1",
        "scheduled_sample_id": "sample-1",
        "pair_phase": "RESEARCH",
        "regime_source_snapshot": source_snapshot,
    }

    _dispatch("darwinian.knot_preregister_pair_assignment", params)

    assert capabilities.calls == [
        (
            "classify_and_reserve_knot_regime",
            {
                "knot_research_track_id": "track-1",
                "research_slot_id": "slot-1",
                "scheduled_sample_id": "sample-1",
                "expected_as_of": "2026-07-19",
                "source_snapshot": source_snapshot,
            },
        )
    ]
    method, forwarded = scorecard.calls[-1]
    assert method == "preregister_knot_pair_assignment"
    assert forwarded["assigned_at"] == "2026-07-19T09:00:00+08:00"
    assert forwarded["regime_classification_receipt"][
        "regime_classification_receipt_id"
    ] == "regime-receipt-1"
    assert callable(forwarded["receipt_verifier"])


@pytest.mark.parametrize(
    "patch",
    [
        {"evaluation_split": "HOLDOUT"},
        {"evaluation_regime": "stress"},
        {"regime_classification_receipt": {}},
        {"assigned_at": "2026-07-19T09:00:00+08:00"},
        {"pair_phase": "AD_HOC"},
        {"regime_source_snapshot": []},
    ],
)
def test_preregister_rejects_caller_derived_or_malformed_fields(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
    patch: dict[str, Any],
) -> None:
    scorecard, _ = stores
    params: dict[str, Any] = {
        "knot_research_track_id": "track-1",
        "research_slot_id": "slot-1",
        "scheduled_sample_id": "sample-1",
        "pair_phase": "RESEARCH",
        "regime_source_snapshot": {},
        **patch,
    }

    with pytest.raises(RpcError) as exc_info:
        _dispatch("darwinian.knot_preregister_pair_assignment", params)

    assert exc_info.value.code == INVALID_PARAMS
    assert not any(call[0] == "preregister_knot_pair_assignment" for call in scorecard.calls)


def test_freeze_pair_mints_and_forwards_only_pair_root_receipt(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
) -> None:
    scorecard, capabilities = stores
    champion = {"manifest": {"capability_id": "champion-1"}}
    candidate = {"manifest": {"capability_id": "candidate-1"}}
    params = {
        "knot_research_track_id": "track-1",
        "knot_pair_assignment_id": "assignment-1",
        "research_slot_id": "slot-1",
        "evaluation_opportunity_set_id": "opportunity-1",
        "champion_capability_envelope": champion,
        "candidate_capability_envelope": candidate,
    }

    result = _dispatch("darwinian.knot_freeze_pair", params)

    assert result["knot_pair_id"] == "pair-1"
    assert result["sector_inference_budget_contract_ref"] is None
    assert "sector_inference_budget_contract" not in result
    method, forwarded = scorecard.calls[-1]
    assert method == "freeze_knot_pair_input"
    assert set(forwarded) == {
        "knot_research_track_id",
        "knot_pair_assignment_id",
        "research_slot_id",
        "evaluation_opportunity_set_id",
        "pair_root_receipt",
        "receipt_verifier",
    }
    assert forwarded["pair_root_receipt"]["pair_root_reservation_id"] == "reservation-1"
    assert callable(forwarded["receipt_verifier"])
    assert capabilities.calls[-1] == (
        "bind_knot_private_pair",
        {
            "pair_root_reservation_id": "reservation-1",
            "knot_pair_id": "pair-1",
            "knot_pair_input_hash": f"sha256:{'a' * 64}",
            "sector_inference_budget_contract": None,
        },
    )


def test_freeze_pair_prebinds_full_sector_budget_but_returns_only_opaque_ref(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
) -> None:
    scorecard, capabilities = stores
    scorecard.sector_budget = {
        "budget_contract_id": "sector-inference-budget",
        "budget_contract_version": "sector_inference_budget_v3",
        "direction_research_output_token_cap": 101,
        "conflict_review_output_token_reserve": 51,
        "final_selection_output_token_cap": 49,
        "total_stage_input_token_cap": 1_001,
        "total_stage_output_token_cap": 201,
        "maximum_model_subcalls": 3,
        "review_reserve_transfer_policy": "NON_TRANSFERABLE",
        "budget_breach_policy": "STAGE_REJECT",
        "budget_contract_hash": f"sha256:{'e' * 64}",
    }

    result = _dispatch(
        "darwinian.knot_freeze_pair",
        {
            "knot_research_track_id": "track-1",
            "knot_pair_assignment_id": "assignment-1",
            "research_slot_id": "slot-1",
            "evaluation_opportunity_set_id": "opportunity-1",
            "champion_capability_envelope": {},
            "candidate_capability_envelope": {},
        },
    )

    assert result["sector_inference_budget_contract_ref"] == {
        "budget_contract_id": "sector-inference-budget",
        "budget_contract_version": "sector_inference_budget_v3",
        "budget_contract_hash": f"sha256:{'e' * 64}",
    }
    assert "sector_inference_budget_contract" not in result
    assert capabilities.calls[-1][1]["sector_inference_budget_contract"] == (
        scorecard.sector_budget
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"root_snapshot_binding": {}},
        {"champion_capability": {}},
        {"candidate_capability": {}},
        {"frozen_at": "2026-07-19T09:01:00+08:00"},
        {"evaluation_split": "EVALUATION"},
        {"regime_snapshot_hash": f"sha256:{'1' * 64}"},
    ],
)
def test_freeze_pair_rejects_caller_root_or_derived_lineage(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
    patch: dict[str, Any],
) -> None:
    scorecard, _ = stores
    params = {
        "knot_research_track_id": "track-1",
        "knot_pair_assignment_id": "assignment-1",
        "research_slot_id": "slot-1",
        "evaluation_opportunity_set_id": "opportunity-1",
        "champion_capability_envelope": {},
        "candidate_capability_envelope": {},
        **patch,
    }

    with pytest.raises(RpcError) as exc_info:
        _dispatch("darwinian.knot_freeze_pair", params)

    assert exc_info.value.code == INVALID_PARAMS
    assert not any(call[0] == "freeze_knot_pair_input" for call in scorecard.calls)


def test_capability_verifier_failures_are_invalid_params(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
) -> None:
    scorecard, capabilities = stores
    capabilities.error = ValueError("invalid capability signature")

    with pytest.raises(RpcError, match="invalid capability signature") as exc_info:
        _dispatch(
            "darwinian.knot_freeze_pair",
            {
                "knot_research_track_id": "track-1",
                "knot_pair_assignment_id": "assignment-1",
                "research_slot_id": "slot-1",
                "evaluation_opportunity_set_id": "opportunity-1",
                "champion_capability_envelope": {},
                "candidate_capability_envelope": {},
            },
        )

    assert exc_info.value.code == INVALID_PARAMS
    assert scorecard.calls == []


def test_accepted_pair_side_mints_strict_receipt_and_derives_run_lineage(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
) -> None:
    scorecard, capabilities = stores
    output = {"agent_id": "china"}
    graph = {"schema_version": "evidence_claim_graph_v1"}
    schema = {"type": "object"}

    _dispatch(
        "darwinian.knot_append_pair_side_result",
        {
            "knot_pair_id": "pair-1",
            "pair_side": "CHAMPION",
            "result_disposition": "ACCEPTED",
            "recorded_at": "2026-07-19T09:10:00+08:00",
            "accepted_output_record": output,
            "verified_claim_graph": graph,
            "schema_json": schema,
        },
    )

    assert capabilities.calls[-1][0] == "mint_knot_strict_output_validation_receipt"
    method, forwarded = scorecard.calls[-1]
    assert method == "append_knot_pair_side_execution_result"
    assert forwarded["graph_run_id"] == "graph-1"
    assert forwarded["run_id"] == "run-1"
    assert forwarded["validated_output"] == {
        "accepted_output_record": output,
        "verified_claim_graph": graph,
        "strict_validation_receipt": {
            "strict_validation_receipt_id": "strict-receipt-1"
        },
    }
    assert callable(forwarded["strict_receipt_verifier"])
    assert forwarded["cio_failure_phase"] is None
    assert forwarded["cio_output_phase"] is None


@pytest.mark.parametrize(
    ("output_phase", "private_phase", "append_method"),
    [
        ("CIO_PROPOSAL", "PROPOSAL", "append_knot_cio_proposal_execution_result"),
        ("CIO_FINAL", "FINAL", "append_knot_pair_side_execution_result"),
    ],
)
def test_cio_accepted_outputs_require_phase_specific_schema_and_persistence(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
    output_phase: str,
    private_phase: str,
    append_method: str,
) -> None:
    scorecard, capabilities = stores
    capabilities.agent_id = "cio"
    capabilities.stage = "cio_final"

    def phase_schema(**kwargs: Any) -> dict[str, Any]:
        scorecard.calls.append(("resolve_knot_strict_schema_binding", kwargs))
        return {
            "accepted_output_kind": output_phase,
            "schema_phase": output_phase,
            "schema_id": f"cio.{private_phase.lower()}.output.v1",
            "schema_hash": f"sha256:{'b' * 64}",
            "immutable_phase_instruction_hash": f"sha256:{'c' * 64}",
            "structured_output_schema_binding_set_hash": f"sha256:{'d' * 64}",
        }

    scorecard.resolve_knot_strict_schema_binding = phase_schema  # type: ignore[attr-defined]
    _dispatch(
        "darwinian.knot_append_pair_side_result",
        {
            "knot_pair_id": "pair-1",
            "pair_side": "CHAMPION",
            "result_disposition": "ACCEPTED",
            "output_phase": output_phase,
            "recorded_at": "2026-07-19T09:10:00+08:00",
            "accepted_output_record": {"agent_id": "cio"},
            "verified_claim_graph": {"schema_version": "evidence_claim_graph_v1"},
            "schema_json": {"type": "object"},
        },
    )

    assert scorecard.calls[0][1]["cio_output_phase"] == private_phase
    method, forwarded = scorecard.calls[-1]
    assert method == append_method
    assert forwarded["cio_output_phase"] == private_phase


@pytest.mark.parametrize("output_phase", [None, "PROPOSAL", "CIO_UNKNOWN"])
def test_cio_accepted_output_rejects_missing_or_unscoped_phase(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
    output_phase: str | None,
) -> None:
    scorecard, capabilities = stores
    capabilities.agent_id = "cio"
    params: dict[str, Any] = {
        "knot_pair_id": "pair-1",
        "pair_side": "CHAMPION",
        "result_disposition": "ACCEPTED",
        "recorded_at": "2026-07-19T09:10:00+08:00",
        "accepted_output_record": {"agent_id": "cio"},
        "verified_claim_graph": {"schema_version": "evidence_claim_graph_v1"},
        "schema_json": {"type": "object"},
    }
    if output_phase is not None:
        params["output_phase"] = output_phase

    with pytest.raises(RpcError) as exc_info:
        _dispatch("darwinian.knot_append_pair_side_result", params)

    assert exc_info.value.code == INVALID_PARAMS
    assert not any(
        method.startswith("append_knot_pair_side")
        or method == "append_knot_cio_proposal_execution_result"
        for method, _ in scorecard.calls
    )


def test_cio_proposal_then_final_share_pair_but_keep_phase_receipts_distinct(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
) -> None:
    scorecard, capabilities = stores
    capabilities.agent_id = "cio"
    capabilities.stage = "cio_final"

    def phase_schema(**kwargs: Any) -> dict[str, Any]:
        phase = kwargs["cio_output_phase"]
        kind = f"CIO_{phase}"
        scorecard.calls.append(("resolve_knot_strict_schema_binding", kwargs))
        return {
            "accepted_output_kind": kind,
            "schema_phase": kind,
            "schema_id": f"cio.{phase.lower()}.output.v1",
            "schema_hash": f"sha256:{('1' if phase == 'PROPOSAL' else '2') * 64}",
            "immutable_phase_instruction_hash": f"sha256:{'3' * 64}",
            "structured_output_schema_binding_set_hash": f"sha256:{'4' * 64}",
        }

    scorecard.resolve_knot_strict_schema_binding = phase_schema  # type: ignore[attr-defined]
    for phase in ("CIO_PROPOSAL", "CIO_FINAL"):
        _dispatch(
            "darwinian.knot_append_pair_side_result",
            {
                "knot_pair_id": "pair-cio-1",
                "pair_side": "CHAMPION",
                "result_disposition": "ACCEPTED",
                "output_phase": phase,
                "recorded_at": "2026-07-19T09:10:00+08:00",
                "accepted_output_record": {"agent_id": "cio", "phase": phase},
                "verified_claim_graph": {
                    "schema_version": "evidence_claim_graph_v1",
                    "phase": phase,
                },
                "schema_json": {"type": "object"},
            },
        )

    minted = [
        kwargs["accepted_output_kind"]
        for method, kwargs in capabilities.calls
        if method == "mint_knot_strict_output_validation_receipt"
    ]
    assert minted == ["CIO_PROPOSAL", "CIO_FINAL"]
    persisted = [
        (method, kwargs["cio_output_phase"], kwargs["graph_run_id"], kwargs["run_id"])
        for method, kwargs in scorecard.calls
        if method
        in {
            "append_knot_cio_proposal_execution_result",
            "append_knot_pair_side_execution_result",
        }
    ]
    assert persisted == [
        ("append_knot_cio_proposal_execution_result", "PROPOSAL", "graph-1", "run-1"),
        ("append_knot_pair_side_execution_result", "FINAL", "graph-1", "run-1"),
    ]


def test_failed_pair_side_forbids_accepted_fields_and_uses_frozen_run_lineage(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
) -> None:
    scorecard, _ = stores
    _dispatch(
        "darwinian.knot_append_pair_side_result",
        {
            "knot_pair_id": "pair-1",
            "pair_side": "CANDIDATE",
            "result_disposition": "AGENT_FAILURE",
            "recorded_at": "2026-07-19T09:10:00+08:00",
            "failure_reason": "MODEL_TIMEOUT",
        },
    )
    _, forwarded = scorecard.calls[-1]
    assert forwarded["validated_output"] is None
    assert forwarded["graph_run_id"] == "graph-1"
    assert forwarded["run_id"] == "run-1"
    assert forwarded["strict_receipt_verifier"] is None
    assert forwarded["cio_failure_phase"] is None
    assert forwarded["cio_output_phase"] is None

    with pytest.raises(RpcError) as exc_info:
        _dispatch(
            "darwinian.knot_append_pair_side_result",
            {
                "knot_pair_id": "pair-2",
                "pair_side": "CANDIDATE",
                "result_disposition": "AGENT_FAILURE",
                "recorded_at": "2026-07-19T09:10:00+08:00",
                "failure_reason": "MODEL_TIMEOUT",
                "accepted_output_record": {},
            },
        )
    assert exc_info.value.code == INVALID_PARAMS


@pytest.mark.parametrize("legacy_field", ["output", "graph_run_id", "run_id"])
def test_pair_side_rejects_legacy_or_caller_owned_lineage(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
    legacy_field: str,
) -> None:
    with pytest.raises(RpcError) as exc_info:
        _dispatch(
            "darwinian.knot_append_pair_side_result",
            {
                "knot_pair_id": "pair-1",
                "pair_side": "CHAMPION",
                "result_disposition": "AGENT_FAILURE",
                "recorded_at": "2026-07-19T09:10:00+08:00",
                "failure_reason": "MODEL_TIMEOUT",
                legacy_field: {},
            },
        )
    assert exc_info.value.code == INVALID_PARAMS


def test_sector_cost_audit_uses_only_server_owned_usage_binding(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
) -> None:
    scorecard, capabilities = stores
    params = {
        "knot_pair_id": "pair-1",
        "pair_side": "CHAMPION",
    }

    _dispatch("darwinian.knot_append_sector_cost_audit", params)

    assert scorecard.calls[-2] == ("resolve_knot_sector_usage_binding", params)
    assert capabilities.calls[-1] == (
        "mint_knot_sector_inference_usage_receipt",
        {"binding": {"method": "resolve_knot_sector_usage_binding", "params": params}},
    )
    method, forwarded = scorecard.calls[-1]
    assert method == "append_knot_sector_inference_cost_audit"
    assert forwarded["knot_pair_id"] == "pair-1"
    assert forwarded["pair_side"] == "CHAMPION"
    assert forwarded["usage_receipt"] == {
        "usage_receipt_id": "sector-usage-receipt-1"
    }
    assert callable(forwarded["receipt_verifier"])


def test_accepted_control_dependency_mints_strict_receipt(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
) -> None:
    scorecard, capabilities = stores
    params = {
        "knot_pair_id": "pair-1",
        "control_side": "SHARED",
        "agent_id": "cro",
        "graph_run_id": "graph-control-1",
        "run_id": "run-control-1",
        "result_disposition": "ACCEPTED",
        "frozen_object_set_id": "object-set-1",
        "frozen_object_set_hash": f"sha256:{'1' * 64}",
        "evidence_ids": ["evidence-1"],
        "recorded_at": "2026-07-19T09:10:00+08:00",
        "output": {"agent": "cro"},
        "schema_json": {"type": "object"},
    }

    _dispatch("darwinian.knot_append_control_dependency", params)

    assert capabilities.calls[-1][0] == (
        "mint_knot_control_strict_output_validation_receipt"
    )
    method, forwarded = scorecard.calls[-1]
    assert method == "append_knot_control_dependency_result"
    assert forwarded["validated_output"] == {
        "accepted_output_record": {"agent": "cro"},
        "strict_validation_receipt": {
            "strict_validation_receipt_id": "control-strict-receipt-1"
        },
    }
    assert callable(forwarded["strict_receipt_verifier"])
    assert "output" not in forwarded


@pytest.mark.parametrize(
    "patch",
    [
        {"schema_json": None},
        {"run_id": None},
        {"failure_reason": "caller-forged"},
    ],
)
def test_accepted_control_dependency_requires_exact_strict_inputs(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
    patch: dict[str, Any],
) -> None:
    scorecard, _ = stores
    params = {
        "knot_pair_id": "pair-1",
        "control_side": "SHARED",
        "agent_id": "cro",
        "graph_run_id": "graph-control-1",
        "run_id": "run-control-1",
        "result_disposition": "ACCEPTED",
        "frozen_object_set_id": "object-set-1",
        "frozen_object_set_hash": f"sha256:{'1' * 64}",
        "evidence_ids": ["evidence-1"],
        "recorded_at": "2026-07-19T09:10:00+08:00",
        "output": {"agent": "cro"},
        "schema_json": {"type": "object"},
        **patch,
    }

    with pytest.raises(RpcError) as exc_info:
        _dispatch("darwinian.knot_append_control_dependency", params)

    assert exc_info.value.code == INVALID_PARAMS
    assert not any(
        method == "append_knot_control_dependency_result"
        for method, _ in scorecard.calls
    )


@pytest.mark.parametrize("forbidden", ["output", "schema_json"])
def test_nonaccepted_control_dependency_rejects_accepted_output_fields(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
    forbidden: str,
) -> None:
    scorecard, _ = stores
    params: dict[str, Any] = {
        "knot_pair_id": "pair-1",
        "control_side": "SHARED",
        "agent_id": "cro",
        "graph_run_id": "graph-control-1",
        "result_disposition": "AGENT_FAILURE",
        "frozen_object_set_id": "object-set-1",
        "frozen_object_set_hash": f"sha256:{'1' * 64}",
        "evidence_ids": ["evidence-1"],
        "recorded_at": "2026-07-19T09:10:00+08:00",
        "failure_reason": "MODEL_TIMEOUT",
        forbidden: {"type": "object"},
    }

    with pytest.raises(RpcError) as exc_info:
        _dispatch("darwinian.knot_append_control_dependency", params)

    assert exc_info.value.code == INVALID_PARAMS
    assert not any(
        method == "append_knot_control_dependency_result"
        for method, _ in scorecard.calls
    )


@pytest.mark.parametrize(
    "caller_owned_field",
    [
        "accepted_output_id",
        "operational_opportunity_audit_id",
        "model_subcall_count",
        "last_attempted_stage",
        "conflict_review_triggered",
        "input_tokens",
        "output_tokens",
        "recorded_at",
        "failure_reason",
    ],
)
def test_sector_cost_audit_rejects_caller_owned_usage(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
    caller_owned_field: str,
) -> None:
    scorecard, _ = stores
    with pytest.raises(RpcError) as exc_info:
        _dispatch(
            "darwinian.knot_append_sector_cost_audit",
            {
                "knot_pair_id": "pair-1",
                "pair_side": "CHAMPION",
                caller_owned_field: 1,
            },
        )
    assert exc_info.value.code == INVALID_PARAMS
    assert scorecard.calls == []


def test_all_knot_handlers_reject_unknown_parameters(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
) -> None:
    with pytest.raises(RpcError) as exc_info:
        _dispatch(
            "darwinian.knot_finalize_pair",
            {
                "knot_pair_id": "pair-1",
                "pair_disposition": "ACCOUNTABLE",
                "recorded_at": "2026-07-19T10:00:00+08:00",
                "caller_gate_override": True,
            },
        )
    assert exc_info.value.code == INVALID_PARAMS


@pytest.mark.parametrize(
    ("rpc_method", "forged_params"),
    [
        (
            "darwinian.prepare_outcome_schedule",
            {
                "trading_calendar_snapshot": {"trading_dates": ["2099-01-01"]},
                "verified_event_candidates": {"china": {"events": []}},
            },
        ),
        (
            "darwinian.freeze_outcome_opportunity",
            {
                "member_refs": [{"forged": True}],
                "source_evidence_by_required_source_id": {
                    "official": ["forged"]
                },
            },
        ),
        (
            "darwinian.record_outcome_opportunity_failure",
            {
                "error_codes": ["FORGED_DENOMINATOR_FAILURE"],
                "source_evidence_by_required_source_id": {},
            },
        ),
    ],
)
def test_production_rpc_rejects_caller_owned_outcome_denominator_inputs(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
    rpc_method: str,
    forged_params: dict[str, Any],
) -> None:
    scorecard, _ = stores

    with pytest.raises(RpcError, match="server-owned") as exc_info:
        _dispatch(rpc_method, forged_params)

    assert exc_info.value.code == INVALID_PARAMS
    assert scorecard.calls == []


class _DecisionStageStore:
    def __init__(
        self,
        *,
        agent_id: str,
        outcome_schedule_plan_id: str = "plan-1",
        as_of: str = "2026-07-19",
    ) -> None:
        self.agent_id = agent_id
        self.outcome_schedule_plan_id = outcome_schedule_plan_id
        self.as_of = as_of
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.stage_skips: dict[str, dict[str, Any]] = {}

    def resolve_scheduled_sample_context(
        self, *, scheduled_sample_id: str
    ) -> dict[str, Any]:
        self.calls.append(
            ("resolve_scheduled_sample_context", {"scheduled_sample_id": scheduled_sample_id})
        )
        return {
            "scheduled_sample_id": scheduled_sample_id,
            "as_of": self.as_of,
            "prepared_at": "2026-07-19T09:00:00+08:00",
            "graph_run_id": "graph-1",
            "agent_id": self.agent_id,
            "outcome_schedule_plan_id": self.outcome_schedule_plan_id,
            "outcome_schedule_slot_id": "outcome-slot-1",
            "outcome_schedule_slot_hash": f"sha256:{'9' * 64}",
            "run_slot_id": "run-slot-1",
            "trigger_event": None,
        }

    def freeze_scheduled_outcome_opportunity(
        self, **kwargs: Any
    ) -> dict[str, Any]:
        self.calls.append(("freeze_scheduled_outcome_opportunity", kwargs))
        return {
            "run_allowed": True,
            "scheduled_sample_id": "sample-1",
            "evaluation_opportunity_set_id": "opportunity-1",
            "evaluation_opportunity_set_hash": f"sha256:{'a' * 64}",
            "frozen_object_set_id": kwargs.get("frozen_object_set_id"),
            "frozen_object_set_hash": kwargs.get("frozen_object_set_hash"),
            "runtime_authority_binding": kwargs.get("runtime_authority_binding"),
        }

    def create_no_evaluation_object_stage_skip(
        self, **kwargs: Any
    ) -> dict[str, Any]:
        self.calls.append(("create_no_evaluation_object_stage_skip", kwargs))
        return {
            "run_allowed": False,
            "scheduled_sample_id": "sample-1",
            "evaluation_opportunity_set_id": "opportunity-1",
            "evaluation_opportunity_set_hash": f"sha256:{'a' * 64}",
            "stage_skip": {"stage_skip_id": "stage-skip-1"},
        }

    def record_scheduled_outcome_opportunity_failure(
        self, **kwargs: Any
    ) -> dict[str, Any]:
        self.calls.append(
            ("record_scheduled_outcome_opportunity_failure", kwargs)
        )
        return {
            "run_allowed": False,
            "scheduled_sample_id": "sample-1",
            "evaluation_opportunity_set_id": None,
            "evaluation_opportunity_set_hash": None,
            "generation_attempt_id": "generation-attempt-1",
            "eligibility_audit_revision_id": "eligibility-revision-1",
            "operational_opportunity_audit_id": "operational-audit-1",
        }

    def resolve_no_evaluation_object_stage_skip(
        self, *, graph_run_id: str, agent_id: str
    ) -> dict[str, Any] | None:
        self.calls.append(
            (
                "resolve_no_evaluation_object_stage_skip",
                {"graph_run_id": graph_run_id, "agent_id": agent_id},
            )
        )
        return self.stage_skips.get(agent_id)


def _stage_projection(member_refs: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "projection_status": "AVAILABLE",
        "qualification_predicate_version": "qualification-v1",
        "member_refs": member_refs,
        "source_evidence_by_required_source_id": {"runtime": ["evidence-1"]},
        "snapshot_hash": f"sha256:{'b' * 64}",
        "error_codes": [],
    }


@pytest.mark.parametrize(
    ("agent_id", "source_tool_id"),
    sorted(LIVE_SOURCE_TOOL_BY_AGENT.items()),
)
def test_l1_l2_live_freeze_binds_exact_server_source_authority(
    monkeypatch: pytest.MonkeyPatch,
    agent_id: str,
    source_tool_id: str,
) -> None:
    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    authority_module = importlib.import_module(
        "mosaic.scorecard.opportunity_authority"
    )
    members = [{"fixture_member": f"member:{agent_id}"}]
    binding = {
        "source_tool_id": source_tool_id,
        "source_snapshot_hash": f"sha256:{'6' * 64}",
        "domain_hash": f"sha256:{'7' * 64}",
    }
    store = _DecisionStageStore(agent_id=agent_id)
    monkeypatch.setattr(module, "_store", lambda: store)
    _install_stage_projection(monkeypatch, _stage_projection(members))
    monkeypatch.setattr(
        authority_module,
        "materialize_pre_run_authority",
        lambda **_kwargs: {
            "member_refs": members,
            "runtime_authority_binding": binding,
        },
    )

    result = _dispatch(
        "darwinian.freeze_outcome_opportunity",
        {
            "outcome_schedule_plan_id": "plan-1",
            "scheduled_sample_id": "sample-1",
            "agent_id": agent_id,
        },
    )

    assert result["run_allowed"] is True
    assert result["runtime_authority_binding"] == binding
    frozen = next(
        kwargs
        for method, kwargs in store.calls
        if method == "freeze_scheduled_outcome_opportunity"
    )
    assert frozen["member_refs"] == members
    assert frozen["runtime_authority_binding"] == binding


def test_l1_l2_live_freeze_rejects_source_domain_drift_before_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    authority_module = importlib.import_module(
        "mosaic.scorecard.opportunity_authority"
    )
    store = _DecisionStageStore(agent_id="energy")
    monkeypatch.setattr(module, "_store", lambda: store)
    _install_stage_projection(
        monkeypatch,
        _stage_projection([{"fixture_member": "scheduled"}]),
    )
    monkeypatch.setattr(
        authority_module,
        "materialize_pre_run_authority",
        lambda **_kwargs: {
            "member_refs": [{"fixture_member": "changed-before-agent"}],
            "runtime_authority_binding": {
                "source_tool_id": "get_sector_research_snapshot",
                "source_snapshot_hash": f"sha256:{'6' * 64}",
                "domain_hash": f"sha256:{'7' * 64}",
            },
        },
    )

    result = _dispatch(
        "darwinian.freeze_outcome_opportunity",
        {
            "outcome_schedule_plan_id": "plan-1",
            "scheduled_sample_id": "sample-1",
            "agent_id": "energy",
        },
    )

    assert result["run_allowed"] is False
    assert result["blocker_reason"] == "SOURCE_AUTHORITY_MISMATCH"
    assert not any(
        method == "freeze_scheduled_outcome_opportunity"
        for method, _ in store.calls
    )


def test_day_start_preparation_creates_no_opportunity_terminal_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    calendar_module = importlib.import_module("mosaic.dataflows.calendar")
    runtime_inputs = importlib.import_module(
        "mosaic.dataflows.outcome_runtime_inputs"
    )

    class ScheduleOnlyStore:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def prepare_outcome_schedule_plan(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("prepare_outcome_schedule_plan", kwargs))
            return {
                "outcome_schedule_plan_id": "plan-1",
                "event_candidate_input_hash": f"sha256:{'8' * 64}",
                "slots": [
                    {
                        "agent_id": "china",
                        "run_slot_kind": "OUTCOME_SCHEDULED",
                    }
                ],
            }

        def freeze_scheduled_outcome_opportunity(self, **_kwargs: Any) -> None:
            raise AssertionError("day-start must not freeze an opportunity")

        def record_scheduled_outcome_opportunity_failure(
            self, **_kwargs: Any
        ) -> None:
            raise AssertionError("day-start must not write a generation failure")

    store = ScheduleOnlyStore()
    monkeypatch.setattr(module, "_store", lambda: store)
    monkeypatch.setattr(
        calendar_module,
        "verified_trading_calendar_snapshot",
        lambda *_args, **_kwargs: {"snapshot_hash": f"sha256:{'9' * 64}"},
    )
    monkeypatch.setattr(
        runtime_inputs,
        "load_verified_event_coverage",
        lambda _as_of: {},
    )

    result = _dispatch(
        "darwinian.prepare_daily_cycle_outcomes",
        {
            "production_variant_roster_revision_id": "revision-1",
            "graph_run_id": "graph-1",
            "as_of": "2026-07-19T09:00:00+08:00",
            "prepared_at": "2026-07-19T09:00:00+08:00",
        },
    )

    assert [method for method, _ in store.calls] == [
        "prepare_outcome_schedule_plan"
    ]
    assert result["scheduled_opportunity_decisions"] == []
    assert result["run_blockers"] == []


def _decision_runtime_authority(
    agent_id: str,
    *,
    empty: bool = False,
) -> dict[str, Any]:
    from mosaic.scorecard.darwinian_v2 import canonical_hash

    candidates_by_agent = {
        "alpha_discovery": [
            {
                "candidate_ref": "alpha-1",
                "ts_code": "600001.SH",
            }
        ],
        "cro": [
            {
                "candidate_ref": "risk-1",
                "ts_code": "600002.SH",
                "proposed_target_weight": 0.1,
            }
        ],
        "autonomous_execution": [
            {
                "candidate_ref": "execution-1",
                "ts_code": "600003.SH",
                "order_intent_ref": "order-1",
                "current_weight": 0.1,
                "target_weight": 0.2,
                "requested_delta_weight": 0.1,
            }
        ],
        "cio": [
            {
                "candidate_ref": "cio-1",
                "ts_code": "600004.SH",
                "proposal_position_ref": "position-1",
                "current_weight": 0.2,
                "proposed_target_weight": 0.3,
            }
        ],
    }
    candidates = [] if empty else candidates_by_agent[agent_id]
    status = "EMPTY_CONFIRMED" if empty else "AVAILABLE"
    accepted_control_sources = {
        "cro": {
            "source_status": "ACCEPTED_OUTPUT",
            "agent_id": "cro",
            "accepted_output_kind": "CRO_RISK_REVIEW",
            "accepted_output_id": "accepted-control:cro",
            "accepted_output_hash": f"sha256:{'5' * 64}",
            "stage_skip_id": None,
            "stage_skip_hash": None,
        },
        "autonomous_execution": {
            "source_status": "ACCEPTED_OUTPUT",
            "agent_id": "autonomous_execution",
            "accepted_output_kind": "EXECUTION_ASSESSMENT",
            "accepted_output_id": "accepted-control:autonomous-execution",
            "accepted_output_hash": f"sha256:{'6' * 64}",
            "stage_skip_id": None,
            "stage_skip_hash": None,
        },
    }
    role_context: dict[str, Any] = {}
    if agent_id == "autonomous_execution":
        role_context["cro_control_source"] = accepted_control_sources["cro"]
    elif agent_id == "cio":
        role_context.update(
            {
                "cro_control_source": accepted_control_sources["cro"],
                "execution_control_source": accepted_control_sources[
                    "autonomous_execution"
                ],
            }
        )
    return {
        "agent_id": agent_id,
        "stage": "cio_final" if agent_id == "cio" else agent_id,
        "snapshot_id": f"{agent_id}-snapshot:1",
        "snapshot_hash": f"sha256:{'1' * 64}",
        "candidate_status": status,
        "candidate_scope_hash": f"sha256:{'2' * 64}",
        "candidate_universe_id": f"{agent_id}-candidate-universe:1",
        "candidate_universe_hash": canonical_hash(
            {"candidate_status": status, "candidate_universe": candidates}
        ),
        "upstream_accepted_output_refs": [
            {
                "accepted_output_id": "accepted-upstream:1",
                "accepted_output_hash": f"sha256:{'4' * 64}",
            }
        ],
        "role_context": role_context,
        "candidate_universe": candidates,
    }


def _decision_stage_object(authority: dict[str, Any]) -> dict[str, Any]:
    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    from mosaic.scorecard.darwinian_v2 import canonical_hash

    agent_id = authority["agent_id"]
    payload, members = module._expected_decision_frozen_object(
        agent_id,
        authority,
    )
    frozen_hash = canonical_hash(payload)
    namespace = {
        "alpha_discovery": "alpha-novel-candidate-universe",
        "cro": "cro-candidate-universe",
        "autonomous_execution": "order-intent-set",
        "cio": "cio-frozen-portfolio",
    }[agent_id]
    object_kind = {
        "alpha_discovery": "ALPHA_NOVEL_CANDIDATE_UNIVERSE",
        "cro": "CRO_CANDIDATE_UNIVERSE",
        "autonomous_execution": "EXECUTION_ORDER_INTENT_SET",
        "cio": "CIO_FROZEN_PORTFOLIO_CONTEXT",
    }[agent_id]
    return {
        "schema_version": "decision_stage_frozen_object_set_v1",
        "agent_id": agent_id,
        "object_kind": object_kind,
        "frozen_object_set_id": f"{namespace}:{frozen_hash[7:]}",
        "frozen_object_set_hash": frozen_hash,
        "object_payload": payload,
        "member_refs": members,
    }


def _cro_stage_object() -> dict[str, Any]:
    return _decision_stage_object(_decision_runtime_authority("cro"))


def _alpha_stage_object() -> dict[str, Any]:
    return _decision_stage_object(
        _decision_runtime_authority("alpha_discovery", empty=True)
    )


def _install_decision_runtime_authority(
    monkeypatch: pytest.MonkeyPatch,
    authority: dict[str, Any],
) -> None:
    capabilities = importlib.import_module("mosaic.bridge.tool_capabilities")
    monkeypatch.setattr(
        capabilities,
        "materialize_tool_payload",
        lambda *_args, **_kwargs: json.dumps(authority),
    )


def test_cio_readiness_projection_reaches_full_stage_freeze(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from mosaic.dataflows.outcome_runtime_inputs import (
        OPPORTUNITY_PROJECTION_SCHEMA_VERSION,
        expected_qualification_predicate_version,
    )
    from mosaic.scorecard.darwinian_v2 import canonical_hash
    from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS

    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    agent_id = "cio"
    as_of = "2026-07-19T09:00:00+08:00"
    runtime_root = tmp_path / "outcome-runtime"
    projection = {
        "schema_version": OPPORTUNITY_PROJECTION_SCHEMA_VERSION,
        "agent_id": agent_id,
        "as_of": as_of,
        "generated_at": as_of,
        "pit_status": "VERIFIED",
        "projection_status": "AVAILABLE",
        "qualification_predicate_version": (
            expected_qualification_predicate_version(agent_id)
        ),
        "member_refs": [],
        "source_evidence_by_required_source_id": {
            source_id: [f"evidence:{index}:{source_id}"]
            for index, source_id in enumerate(
                OUTCOME_CONTRACTS[agent_id]["required_source_ids"]
            )
        },
        "error_codes": [],
    }
    projection["snapshot_hash"] = canonical_hash(projection)
    projection_path = (
        runtime_root / "2026-07-19" / "opportunities" / f"{agent_id}.json"
    )
    projection_path.parent.mkdir(parents=True)
    projection_path.write_text(json.dumps(projection), encoding="utf-8")
    monkeypatch.setenv("MOSAIC_OUTCOME_RUNTIME_DIR", str(runtime_root))

    store = _DecisionStageStore(agent_id=agent_id, as_of=as_of)
    monkeypatch.setattr(module, "_store", lambda: store)
    authority = _decision_runtime_authority(agent_id)
    _install_decision_runtime_authority(monkeypatch, authority)

    result = _dispatch(
        "darwinian.freeze_stage_outcome_opportunity",
        {
            "outcome_schedule_plan_id": "plan-1",
            "scheduled_sample_id": "sample-1",
            "agent_id": agent_id,
            "recorded_at": as_of,
            "frozen_object": _decision_stage_object(authority),
        },
    )

    assert result["run_allowed"] is True
    freeze = next(
        kwargs
        for method, kwargs in store.calls
        if method == "freeze_scheduled_outcome_opportunity"
    )
    assert freeze["member_refs"][0]["controlled_target_set_id"] == authority[
        "candidate_universe_id"
    ]
    assert not any(
        method == "create_no_evaluation_object_stage_skip"
        for method, _ in store.calls
    )


def _install_stage_projection(
    monkeypatch: pytest.MonkeyPatch,
    projection: dict[str, Any],
) -> None:
    runtime_inputs = importlib.import_module("mosaic.dataflows.outcome_runtime_inputs")
    monkeypatch.setattr(
        runtime_inputs,
        "load_evaluation_opportunity_projection",
        lambda _as_of, _agent_id: projection,
    )


def _install_superinvestor_authority(
    monkeypatch: pytest.MonkeyPatch,
    *,
    members: list[dict[str, str]],
) -> dict[str, Any]:
    authority = {
        "authority_hash": f"sha256:{'5' * 64}",
        "source_snapshot_hash": f"sha256:{'6' * 64}",
        "candidate_scope_hash": f"sha256:{'7' * 64}",
        "candidate_universe_id": "superinvestor-candidates:1",
        "candidate_universe_hash": f"sha256:{'8' * 64}",
        "member_refs": members,
    }
    authority_module = importlib.import_module(
        "mosaic.scorecard.opportunity_authority"
    )
    monkeypatch.setattr(
        authority_module,
        "materialize_superinvestor_authority",
        lambda **_kwargs: authority,
    )
    return authority


def test_superinvestor_stage_freezes_only_server_authoritative_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    store = _DecisionStageStore(agent_id="munger")
    monkeypatch.setattr(module, "_store", lambda: store)
    _install_stage_projection(monkeypatch, _stage_projection([]))
    members = [
        {"candidate_ref": "candidate:1", "ts_code": "600001.SH"},
        {"candidate_ref": "candidate:2", "ts_code": "600002.SH"},
    ]
    authority = _install_superinvestor_authority(
        monkeypatch, members=members
    )

    result = _dispatch(
        "darwinian.freeze_superinvestor_outcome_opportunity",
        {
            "outcome_schedule_plan_id": "plan-1",
            "scheduled_sample_id": "sample-1",
            "agent_id": "munger",
            "recorded_at": "2026-07-19T09:00:00+08:00",
            "accepted_output_refs": [{"accepted_output_id": "sector-output:1"}],
        },
    )

    freeze = next(
        kwargs
        for method, kwargs in store.calls
        if method == "freeze_scheduled_outcome_opportunity"
    )
    assert freeze["member_refs"] == members
    assert freeze["frozen_object_set_id"] == authority["candidate_universe_id"]
    assert freeze["frozen_object_set_hash"] == authority["candidate_universe_hash"]
    assert result["runtime_candidate_scope_hash"] == authority[
        "candidate_scope_hash"
    ]
    assert result["runtime_candidate_universe_hash"] == authority[
        "candidate_universe_hash"
    ]
    assert result["runtime_source_snapshot_hash"] == authority[
        "source_snapshot_hash"
    ]


def test_superinvestor_empty_authority_freezes_then_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    store = _DecisionStageStore(agent_id="ackman")
    monkeypatch.setattr(module, "_store", lambda: store)
    _install_stage_projection(monkeypatch, _stage_projection([]))
    _install_superinvestor_authority(monkeypatch, members=[])

    result = _dispatch(
        "darwinian.freeze_superinvestor_outcome_opportunity",
        {
            "outcome_schedule_plan_id": "plan-1",
            "scheduled_sample_id": "sample-1",
            "agent_id": "ackman",
            "recorded_at": "2026-07-19T09:00:00+08:00",
            "accepted_output_refs": [{"accepted_output_id": "sector-output:1"}],
        },
    )

    assert [method for method, _ in store.calls][-2:] == [
        "freeze_scheduled_outcome_opportunity",
        "create_no_evaluation_object_stage_skip",
    ]
    assert result["run_allowed"] is False
    assert result["stage_skip"]["stage_skip_id"] == "stage-skip-1"


@pytest.mark.parametrize(
    ("exception_type", "error_code", "blocker_reason"),
    [
        (
            DataVendorUnavailable,
            "REQUIRED_DATA_UNAVAILABLE",
            "SOURCE_AUTHORITY_UNAVAILABLE",
        ),
        (ValueError, "CONTRACT_MISMATCH", "SOURCE_AUTHORITY_MISMATCH"),
    ],
)
def test_superinvestor_source_authority_failure_records_terminal_trio(
    monkeypatch: pytest.MonkeyPatch,
    exception_type: type[Exception],
    error_code: str,
    blocker_reason: str,
) -> None:
    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    authority_module = importlib.import_module(
        "mosaic.scorecard.opportunity_authority"
    )
    store = _DecisionStageStore(agent_id="munger")
    monkeypatch.setattr(module, "_store", lambda: store)
    _install_stage_projection(monkeypatch, _stage_projection([]))

    def fail_materialization(**_kwargs: Any) -> dict[str, Any]:
        raise exception_type("source authority failure")

    monkeypatch.setattr(
        authority_module,
        "materialize_superinvestor_authority",
        fail_materialization,
    )

    result = _dispatch(
        "darwinian.freeze_superinvestor_outcome_opportunity",
        {
            "outcome_schedule_plan_id": "plan-1",
            "scheduled_sample_id": "sample-1",
            "agent_id": "munger",
            "recorded_at": "2026-07-19T09:00:00+08:00",
            "accepted_output_refs": [
                {"accepted_output_id": "sector-output:1"}
            ],
        },
    )

    assert result["run_allowed"] is False
    assert result["blocker_reason"] == blocker_reason
    failures = [
        kwargs
        for method, kwargs in store.calls
        if method == "record_scheduled_outcome_opportunity_failure"
    ]
    assert len(failures) == 1
    assert failures[0]["error_codes"] == [error_code]
    assert not {
        "freeze_scheduled_outcome_opportunity",
        "create_no_evaluation_object_stage_skip",
    } & {method for method, _ in store.calls}


def test_superinvestor_stage_rejects_caller_owned_empty_or_member_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    store = _DecisionStageStore(agent_id="munger")
    monkeypatch.setattr(module, "_store", lambda: store)

    with pytest.raises(RpcError, match="unsupported parameter"):
        _dispatch(
            "darwinian.freeze_superinvestor_outcome_opportunity",
            {
                "outcome_schedule_plan_id": "plan-1",
                "scheduled_sample_id": "sample-1",
                "agent_id": "munger",
                "recorded_at": "2026-07-19T09:00:00+08:00",
                "accepted_output_refs": [
                    {"accepted_output_id": "sector-output:1"}
                ],
                "member_refs": [],
            },
        )

    assert store.calls == []


def test_stage_opportunity_rejects_preforged_schedule_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    store = _DecisionStageStore(agent_id="cro", outcome_schedule_plan_id="other-plan")
    monkeypatch.setattr(module, "_store", lambda: store)
    _install_stage_projection(monkeypatch, _stage_projection([]))

    with pytest.raises(RpcError, match="outcome_schedule_plan_id mismatch"):
        _dispatch(
            "darwinian.freeze_stage_outcome_opportunity",
            {
                "outcome_schedule_plan_id": "plan-1",
                "scheduled_sample_id": "sample-1",
                "agent_id": "cro",
                "recorded_at": "2026-07-19T09:00:00+08:00",
                "frozen_object": _cro_stage_object(),
            },
        )

    assert [method for method, _ in store.calls] == [
        "resolve_scheduled_sample_context"
    ]


@pytest.mark.parametrize(
    "agent_id", ["alpha_discovery", "cro", "autonomous_execution", "cio"]
)
def test_stage_opportunity_rejects_missing_runtime_freeze(
    monkeypatch: pytest.MonkeyPatch,
    agent_id: str,
) -> None:
    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    store = _DecisionStageStore(agent_id=agent_id)
    monkeypatch.setattr(module, "_store", lambda: store)
    _install_stage_projection(monkeypatch, _stage_projection([]))

    with pytest.raises(RpcError, match=f"{agent_id} requires a runtime frozen object"):
        _dispatch(
            "darwinian.freeze_stage_outcome_opportunity",
            {
                "outcome_schedule_plan_id": "plan-1",
                "scheduled_sample_id": "sample-1",
                "agent_id": agent_id,
                "recorded_at": "2026-07-19T09:00:00+08:00",
            },
        )

    assert not any(
        method == "freeze_scheduled_outcome_opportunity"
        for method, _ in store.calls
    )


def test_stage_opportunity_rejects_frozen_object_hash_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    store = _DecisionStageStore(agent_id="cro")
    monkeypatch.setattr(module, "_store", lambda: store)
    _install_stage_projection(monkeypatch, _stage_projection([]))
    _install_decision_runtime_authority(
        monkeypatch,
        _decision_runtime_authority("cro"),
    )
    frozen_object = _cro_stage_object()
    frozen_object["frozen_object_set_hash"] = f"sha256:{'c' * 64}"

    with pytest.raises(RpcError, match="Decision frozen object hash mismatch"):
        _dispatch(
            "darwinian.freeze_stage_outcome_opportunity",
            {
                "outcome_schedule_plan_id": "plan-1",
                "scheduled_sample_id": "sample-1",
                "agent_id": "cro",
                "recorded_at": "2026-07-19T09:00:00+08:00",
                "frozen_object": frozen_object,
            },
        )

    assert not any(
        method == "freeze_scheduled_outcome_opportunity"
        for method, _ in store.calls
    )
    assert not any(
        method == "record_scheduled_outcome_opportunity_failure"
        for method, _ in store.calls
    )


@pytest.mark.parametrize(
    ("exception_type", "error_code", "blocker_reason"),
    [
        (
            DataVendorUnavailable,
            "REQUIRED_DATA_UNAVAILABLE",
            "SOURCE_AUTHORITY_UNAVAILABLE",
        ),
        (ValueError, "CONTRACT_MISMATCH", "SOURCE_AUTHORITY_MISMATCH"),
    ],
)
def test_decision_source_authority_failure_records_terminal_trio(
    monkeypatch: pytest.MonkeyPatch,
    exception_type: type[Exception],
    error_code: str,
    blocker_reason: str,
) -> None:
    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    capabilities = importlib.import_module("mosaic.bridge.tool_capabilities")
    agent_id = "cro"
    authority = _decision_runtime_authority(agent_id)
    store = _DecisionStageStore(agent_id=agent_id)
    monkeypatch.setattr(module, "_store", lambda: store)
    _install_stage_projection(monkeypatch, _stage_projection([]))

    def fail_materialization(*_args: Any, **_kwargs: Any) -> str:
        raise exception_type("source authority failure")

    monkeypatch.setattr(
        capabilities,
        "materialize_tool_payload",
        fail_materialization,
    )

    result = _dispatch(
        "darwinian.freeze_stage_outcome_opportunity",
        {
            "outcome_schedule_plan_id": "plan-1",
            "scheduled_sample_id": "sample-1",
            "agent_id": agent_id,
            "recorded_at": "2026-07-19T09:00:00+08:00",
            "frozen_object": _decision_stage_object(authority),
        },
    )

    assert result["run_allowed"] is False
    assert result["blocker_reason"] == blocker_reason
    failures = [
        kwargs
        for method, kwargs in store.calls
        if method == "record_scheduled_outcome_opportunity_failure"
    ]
    assert len(failures) == 1
    assert failures[0]["error_codes"] == [error_code]
    assert not {
        "freeze_scheduled_outcome_opportunity",
        "create_no_evaluation_object_stage_skip",
    } & {method for method, _ in store.calls}


@pytest.mark.parametrize("forged_field", ["stage_skip_id", "stage_skip_hash"])
def test_decision_stage_freeze_rejects_forged_persisted_skip_binding(
    monkeypatch: pytest.MonkeyPatch,
    forged_field: str,
) -> None:
    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    agent_id = "autonomous_execution"
    store = _DecisionStageStore(agent_id=agent_id)
    persisted = {
        "stage_skip_id": "stage-skip:cro:authoritative",
        "stage_skip_hash": f"sha256:{'9' * 64}",
    }
    store.stage_skips["cro"] = persisted
    monkeypatch.setattr(module, "_store", lambda: store)
    _install_stage_projection(monkeypatch, _stage_projection([]))
    authority = _decision_runtime_authority(agent_id)
    source = {
        "source_status": "NO_EVALUATION_OBJECT",
        "agent_id": "cro",
        "accepted_output_kind": "CRO_RISK_REVIEW",
        "accepted_output_id": None,
        "accepted_output_hash": None,
        "stage_skip_id": persisted["stage_skip_id"],
        "stage_skip_hash": persisted["stage_skip_hash"],
    }
    source[forged_field] = (
        "stage-skip:cro:forged"
        if forged_field == "stage_skip_id"
        else f"sha256:{'8' * 64}"
    )
    authority["role_context"] = {"cro_control_source": source}
    _install_decision_runtime_authority(monkeypatch, authority)

    result = _dispatch(
        "darwinian.freeze_stage_outcome_opportunity",
        {
            "outcome_schedule_plan_id": "plan-1",
            "scheduled_sample_id": "sample-1",
            "agent_id": agent_id,
            "recorded_at": "2026-07-19T09:00:00+08:00",
            "frozen_object": _decision_stage_object(authority),
        },
    )

    assert result["run_allowed"] is False
    assert result["blocker_reason"] == "SOURCE_AUTHORITY_MISMATCH"
    failures = [
        kwargs
        for method, kwargs in store.calls
        if method == "record_scheduled_outcome_opportunity_failure"
    ]
    assert len(failures) == 1
    assert failures[0]["error_codes"] == ["CONTRACT_MISMATCH"]


@pytest.mark.parametrize(
    ("agent_id", "missing_field"),
    [
        ("autonomous_execution", "cro_control_source"),
        ("cio", "cro_control_source"),
        ("cio", "execution_control_source"),
    ],
)
def test_decision_stage_freeze_terminalizes_missing_required_control_source(
    monkeypatch: pytest.MonkeyPatch,
    agent_id: str,
    missing_field: str,
) -> None:
    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    store = _DecisionStageStore(agent_id=agent_id)
    monkeypatch.setattr(module, "_store", lambda: store)
    _install_stage_projection(monkeypatch, _stage_projection([]))
    authority = _decision_runtime_authority(agent_id)
    authority["role_context"].pop(missing_field)
    _install_decision_runtime_authority(monkeypatch, authority)

    result = _dispatch(
        "darwinian.freeze_stage_outcome_opportunity",
        {
            "outcome_schedule_plan_id": "plan-1",
            "scheduled_sample_id": "sample-1",
            "agent_id": agent_id,
            "recorded_at": "2026-07-19T09:00:00+08:00",
            "frozen_object": _decision_stage_object(authority),
        },
    )

    assert result["run_allowed"] is False
    assert result["blocker_reason"] == "SOURCE_AUTHORITY_MISMATCH"
    failures = [
        kwargs
        for method, kwargs in store.calls
        if method == "record_scheduled_outcome_opportunity_failure"
    ]
    assert len(failures) == 1
    assert failures[0]["error_codes"] == ["CONTRACT_MISMATCH"]
    assert not any(
        method == "freeze_scheduled_outcome_opportunity"
        for method, _ in store.calls
    )


def test_decision_stage_freeze_accepts_exact_persisted_skip_control_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    agent_id = "autonomous_execution"
    store = _DecisionStageStore(agent_id=agent_id)
    persisted = {
        "stage_skip_id": "stage-skip:cro:authoritative",
        "stage_skip_hash": f"sha256:{'9' * 64}",
    }
    store.stage_skips["cro"] = persisted
    monkeypatch.setattr(module, "_store", lambda: store)
    _install_stage_projection(monkeypatch, _stage_projection([]))
    authority = _decision_runtime_authority(agent_id)
    authority["role_context"]["cro_control_source"] = {
        "source_status": "NO_EVALUATION_OBJECT",
        "agent_id": "cro",
        "accepted_output_kind": "CRO_RISK_REVIEW",
        "accepted_output_id": None,
        "accepted_output_hash": None,
        "stage_skip_id": persisted["stage_skip_id"],
        "stage_skip_hash": persisted["stage_skip_hash"],
    }
    _install_decision_runtime_authority(monkeypatch, authority)

    result = _dispatch(
        "darwinian.freeze_stage_outcome_opportunity",
        {
            "outcome_schedule_plan_id": "plan-1",
            "scheduled_sample_id": "sample-1",
            "agent_id": agent_id,
            "recorded_at": "2026-07-19T09:00:00+08:00",
            "frozen_object": _decision_stage_object(authority),
        },
    )

    assert result["run_allowed"] is True
    assert any(
        method == "freeze_scheduled_outcome_opportunity"
        for method, _ in store.calls
    )


def test_empty_alpha_stage_freezes_then_skips_before_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    store = _DecisionStageStore(agent_id="alpha_discovery")
    monkeypatch.setattr(module, "_store", lambda: store)
    _install_decision_runtime_authority(
        monkeypatch,
        _decision_runtime_authority("alpha_discovery", empty=True),
    )
    _install_stage_projection(monkeypatch, _stage_projection([]))

    result = _dispatch(
        "darwinian.freeze_stage_outcome_opportunity",
        {
            "outcome_schedule_plan_id": "plan-1",
            "scheduled_sample_id": "sample-1",
            "agent_id": "alpha_discovery",
            "recorded_at": "2026-07-19T09:00:00+08:00",
            "frozen_object": _alpha_stage_object(),
        },
    )

    assert result["run_allowed"] is False
    assert result["stage_skip"]["stage_skip_id"] == "stage-skip-1"
    assert result["frozen_object_set_id"].startswith(
        "alpha-novel-candidate-universe:"
    )
    assert result["frozen_object"]["member_refs"] == []
    assert [method for method, _ in store.calls] == [
        "resolve_scheduled_sample_context",
        "freeze_scheduled_outcome_opportunity",
        "create_no_evaluation_object_stage_skip",
    ]


@pytest.mark.parametrize(
    "agent_id", ["alpha_discovery", "cro", "autonomous_execution", "cio"]
)
@pytest.mark.parametrize("mutation", ["EMPTY", "MEMBER", "HASH"])
def test_stage_opportunity_rejects_caller_forged_decision_denominator(
    monkeypatch: pytest.MonkeyPatch,
    agent_id: str,
    mutation: str,
) -> None:
    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    authority = _decision_runtime_authority(agent_id)
    store = _DecisionStageStore(agent_id=agent_id)
    monkeypatch.setattr(module, "_store", lambda: store)
    _install_stage_projection(monkeypatch, _stage_projection([]))
    _install_decision_runtime_authority(monkeypatch, authority)
    frozen_object = _decision_stage_object(authority)
    if mutation == "EMPTY":
        frozen_object["member_refs"] = []
    elif mutation == "HASH":
        frozen_object["frozen_object_set_hash"] = f"sha256:{'f' * 64}"
    else:
        member = frozen_object["member_refs"][0]
        field = {
            "alpha_discovery": "candidate_ref",
            "cro": "risk_candidate_id",
            "autonomous_execution": "order_intent_id",
            "cio": "controlled_target_set_id",
        }[agent_id]
        member[field] = f"forged:{agent_id}"

    with pytest.raises(RpcError):
        _dispatch(
            "darwinian.freeze_stage_outcome_opportunity",
            {
                "outcome_schedule_plan_id": "plan-1",
                "scheduled_sample_id": "sample-1",
                "agent_id": agent_id,
                "recorded_at": "2026-07-19T09:00:00+08:00",
                "frozen_object": frozen_object,
            },
        )

    assert not any(
        method == "freeze_scheduled_outcome_opportunity"
        for method, _ in store.calls
    )
    assert not any(
        method == "record_scheduled_outcome_opportunity_failure"
        for method, _ in store.calls
    )


@pytest.mark.parametrize(
    ("rpc_method", "params"),
    [
        (
            "darwinian.prepare_variant",
            {
                "binding": {},
                "as_of": "2026-07-19",
                "legacy_weights": {"china": 2.5},
            },
        ),
        (
            "darwinian.prepare_daily_cycle_outcomes",
            {
                "production_variant_roster_revision_id": "revision-1",
                "graph_run_id": "graph-1",
                "as_of": "2026-07-19",
                "prepared_at": "2026-07-19T09:00:00+08:00",
                "verified_event_candidates": {"forged": True},
            },
        ),
    ],
)
def test_production_prepare_rpcs_reject_unknown_or_caller_owned_inputs(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
    rpc_method: str,
    params: dict[str, Any],
) -> None:
    scorecard, _ = stores

    with pytest.raises(RpcError, match="unsupported parameter") as exc_info:
        _dispatch(rpc_method, params)

    assert exc_info.value.code == INVALID_PARAMS
    assert scorecard.calls == []


@pytest.mark.parametrize(
    ("rpc_method", "operation", "result_key"),
    [
        (
            "darwinian.refresh_v2_windows",
            "REFRESH",
            "evaluation_windows",
        ),
        (
            "darwinian.publish_v2_updates",
            "PUBLISH",
            "published_batches",
        ),
    ],
)
def test_darwinian_updates_use_only_server_verified_calendar(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
    monkeypatch: pytest.MonkeyPatch,
    rpc_method: str,
    operation: str,
    result_key: str,
) -> None:
    scorecard, _ = stores
    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    calls: list[dict[str, Any]] = []

    def run_update(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {
            "outcome_maturation": {"maturation_batch_hash": "sha256:" + "a" * 64},
            result_key: {"operation": kwargs["operation"]},
        }

    monkeypatch.setattr(
        module,
        "_run_v2_outcome_update",
        run_update,
    )

    result = _dispatch(
        rpc_method,
        {
            "production_variant_roster_revision_id": "revision-1",
            "cutoff_at": "2026-07-17T15:00:00+08:00",
        },
    )

    assert result[result_key]["operation"] == operation
    assert calls == [
        {
            "production_variant_roster_revision_id": "revision-1",
            "cutoff_at": "2026-07-17T15:00:00+08:00",
            "operation": operation,
        }
    ]
    assert scorecard.calls == []

    with pytest.raises(RpcError, match="unsupported parameter") as exc_info:
        _dispatch(
            rpc_method,
            {
                "production_variant_roster_revision_id": "revision-1",
                "cutoff_at": "2026-07-17T15:00:00+08:00",
                "trading_dates": ["2099-01-01"],
            },
        )
    assert exc_info.value.code == INVALID_PARAMS


@pytest.mark.parametrize(
    "caller_timestamp_field",
    ["recorded_at", "published_at", "authority_published_at"],
)
def test_darwinian_publication_rejects_caller_owned_knowledge_timestamps(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
    caller_timestamp_field: str,
) -> None:
    scorecard, _ = stores
    with pytest.raises(RpcError, match="unsupported parameter") as exc_info:
        _dispatch(
            "darwinian.publish_v2_updates",
            {
                "production_variant_roster_revision_id": "revision-1",
                "cutoff_at": "2026-07-17T15:00:00+08:00",
                caller_timestamp_field: "2020-01-01T00:00:00+00:00",
            },
        )
    assert exc_info.value.code == INVALID_PARAMS
    assert scorecard.calls == []


def test_publish_is_blocked_when_due_outcome_projection_is_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler_module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    updates_module = importlib.import_module("mosaic.scorecard.darwinian_updates")

    class _ConnectionContext:
        def __enter__(self) -> object:
            return object()

        def __exit__(self, *args: object) -> None:
            return None

    class _Store:
        def _connect(self) -> _ConnectionContext:
            return _ConnectionContext()

    monkeypatch.setattr(handler_module, "_store", _Store)
    monkeypatch.setattr(
        handler_module,
        "_verified_darwinian_trading_dates",
        lambda cutoff_at: ["2026-07-17"],
    )
    monkeypatch.setattr(
        updates_module,
        "materialize_due_outcomes",
        lambda *args, **kwargs: {"unresolved_count": 1},
    )

    def unexpected_publish(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("publication must not run with unresolved due outcomes")

    monkeypatch.setattr(
        updates_module,
        "publish_usage_weight_updates",
        unexpected_publish,
    )

    result = handler_module._run_v2_outcome_update(
        production_variant_roster_revision_id="revision-1",
        cutoff_at="2026-07-17T15:00:00+08:00",
        operation="PUBLISH",
    )

    assert result["published_batches"] == []
    assert result["publication_status"] == "BLOCKED_UNRESOLVED_DUE_OUTCOMES"
