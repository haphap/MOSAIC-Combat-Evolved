"""Fail-closed wire tests for the private KNOT runtime bridge surface."""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from mosaic.bridge import handlers as _handlers_pkg  # noqa: F401
from mosaic.bridge.protocol import INVALID_PARAMS, RpcError
from mosaic.bridge.registry import get_handler


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
    ("rpc_method", "store_method", "result_key"),
    [
        (
            "darwinian.refresh_v2_windows",
            "refresh_darwinian_v2_evaluation_windows",
            "evaluation_windows",
        ),
        (
            "darwinian.publish_v2_updates",
            "publish_darwinian_v2_weight_updates",
            "published_batches",
        ),
    ],
)
def test_darwinian_updates_use_only_server_verified_calendar(
    stores: tuple[_RecordingStore, _RecordingCapabilityStore],
    monkeypatch: pytest.MonkeyPatch,
    rpc_method: str,
    store_method: str,
    result_key: str,
) -> None:
    scorecard, _ = stores
    module = importlib.import_module("mosaic.bridge.handlers.darwinian")
    verified_dates = ["2010-01-04", "2026-07-17"]
    monkeypatch.setattr(
        module,
        "_verified_darwinian_trading_dates",
        lambda cutoff_at: verified_dates,
    )

    result = _dispatch(
        rpc_method,
        {
            "production_variant_roster_revision_id": "revision-1",
            "cutoff_at": "2026-07-17T15:00:00+08:00",
        },
    )

    assert result[result_key]["method"] == store_method
    assert scorecard.calls[-1] == (
        store_method,
        {
            "production_variant_roster_revision_id": "revision-1",
            "cutoff_at": "2026-07-17T15:00:00+08:00",
            "trading_dates": verified_dates,
        },
    )

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
