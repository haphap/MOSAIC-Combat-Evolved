from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mosaic.bridge.handlers import prompt_optimizer
from mosaic.bridge.protocol import RpcError
from mosaic.bridge.registry import all_methods, get_handler
from mosaic.scorecard.canonical_json import canonical_string_sort_key
from mosaic.scorecard.prompt_optimizer_store import PromptOptimizerStore
from mosaic.scorecard.store import ScorecardStore


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def candidate() -> dict[str, object]:
    prompt_hashes = {"zh": HASH_A, "en": HASH_B}
    return {
        "schemaVersion": "prompt_candidate_v1",
        "candidateId": "candidate-bridge",
        "parentId": "champion-bridge",
        "parentPromptCommit": "d" * 40,
        "parentPromptHashes": {"zh": HASH_B, "en": HASH_A},
        "target": {
            "agentId": "china",
            "stage": "agent_run",
            "cohort": "cohort_default",
        },
        "promptRefs": {
            "zh": "private://candidate-bridge.zh",
            "en": "private://candidate-bridge.en",
        },
        "promptHashes": prompt_hashes,
        "trainingProjectionHash": HASH_A,
        "excludedSampleIdsHash": HASH_A,
        "mutatorConfigHash": HASH_B,
        "mutatorCommit": "c" * 40,
        "mutationCategories": ["EVIDENCE_PRIORITY"],
        "mutationSummary": "Behavior focus: EVIDENCE_PRIORITY.",
        "hypothesis": (
            "Preregistered hypothesis: EVIDENCE_PRIORITY improves the frozen Agent outcome score."
        ),
        "behaviorContractHash": HASH_A,
        "privateLineageHash": HASH_A,
        "privateStateArtifactHash": HASH_A,
        "createdAt": "2025-04-01T00:00:00Z",
    }


@pytest.fixture
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PromptOptimizerStore:
    value = PromptOptimizerStore(tmp_path / "scorecard.sqlite3")
    monkeypatch.setattr(prompt_optimizer, "_STORE", value)
    monkeypatch.setattr(prompt_optimizer, "_store", lambda: value)
    return value


def dispatch(method: str, params: dict[str, object]) -> object:
    handler = get_handler(method)
    assert handler is not None
    return handler(params)


def test_prompt_optimizer_bridge_registers_minimal_surface_and_round_trips(
    isolated_store: PromptOptimizerStore,
) -> None:
    expected = {
        "prompt_optimizer.get_candidate",
        "prompt_optimizer.get_family",
        "prompt_optimizer.get_split",
        "prompt_optimizer.get_experiment",
        "prompt_optimizer.list_experiments",
        "prompt_optimizer.list_runs",
        "prompt_optimizer.latest_summary",
        "prompt_optimizer.training_projection",
        "prompt_optimizer.put_candidate",
        "prompt_optimizer.put_family",
        "prompt_optimizer.put_split",
        "prompt_optimizer.put_experiment",
        "prompt_optimizer.put_run",
        "prompt_optimizer.claim_run",
    }
    assert expected <= set(all_methods())
    assert dispatch("prompt_optimizer.put_candidate", {"record": candidate()}) == candidate()
    assert dispatch(
        "prompt_optimizer.get_candidate", {"candidate_id": "candidate-bridge"}
    ) == {"record": candidate()}
    assert dispatch(
        "prompt_optimizer.latest_summary", {"cohort": "cohort_default"}
    ) == {
        "candidate": candidate(),
        "experiment": None,
        "release": None,
    }


def test_prompt_optimizer_bridge_exports_strict_training_projection(
    isolated_store: PromptOptimizerStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scorecard = ScorecardStore(isolated_store.db_path)
    import mosaic.scorecard

    monkeypatch.setattr(mosaic.scorecard, "get_store", lambda: scorecard)
    response = dispatch(
        "prompt_optimizer.training_projection",
        {
            "agent_id": "china",
            "stage": "agent_run",
            "cohort": "cohort_default",
            "cutoff_at": "2026-08-01T00:00:00+08:00",
            "excluded_sample_ids": ["reserved-validation"],
        },
    )
    assert isinstance(response, dict)
    projection = response["projection"]
    assert projection["target"]["agentId"] == "china"
    assert projection["matureSampleCount"] == 0
    assert projection["directComponents"] == [
        {
            "componentRef": f"role_component_v1:china:{ordinal:03d}",
            "directMatureSampleCount": 0,
            "meanScore": None,
            "lowerTailScore": None,
            "failureCategoryCounts": {},
        }
        for ordinal in range(6)
    ]
    assert projection["controlledExperiments"] == []
    with pytest.raises(RpcError, match="string array"):
        dispatch(
            "prompt_optimizer.training_projection",
            {
                "agent_id": "china",
                "stage": "agent_run",
                "cohort": "cohort_default",
                "cutoff_at": "2026-08-01T00:00:00+08:00",
                "excluded_sample_ids": "not-an-array",
            },
        )


def test_prompt_optimizer_bridge_rejects_private_body_and_extra_rpc_params(
    isolated_store: PromptOptimizerStore,
) -> None:
    with pytest.raises(RpcError, match="Additional properties"):
        dispatch(
            "prompt_optimizer.put_candidate",
            {"record": {**candidate(), "promptBody": "private"}},
        )
    with pytest.raises(RpcError, match="expected only"):
        dispatch(
            "prompt_optimizer.get_candidate",
            {"candidate_id": "candidate-bridge", "trace": True},
        )
    with pytest.raises(RpcError, match="schema_invalid|noncanonical_string"):
        dispatch(
            "prompt_optimizer.put_candidate",
            {"record": {**candidate(), "candidateId": " candidate-bridge "}},
        )


def test_prompt_optimizer_bridge_rejects_invalid_agent_stage_pair(
    isolated_store: PromptOptimizerStore,
) -> None:
    invalid = candidate()
    invalid["target"] = {
        "agentId": "china",
        "stage": "cio_final",
        "cohort": "cohort_default",
    }
    with pytest.raises(RpcError, match="target_stage_invalid"):
        dispatch("prompt_optimizer.put_candidate", {"record": invalid})


def test_prompt_optimizer_bridge_rejects_evaluator_and_outcome_binding_drift(
    isolated_store: PromptOptimizerStore,
) -> None:
    from tests.test_prompt_optimizer_store import (
        candidate as store_candidate,
        experiment as store_experiment,
        family as store_family,
        recanonicalize_experiment,
        split as store_split,
    )

    split_record = store_split()
    candidate_record = store_candidate(split_record=split_record)
    family_record = store_family(split_record)
    dispatch("prompt_optimizer.put_candidate", {"record": candidate_record})
    dispatch("prompt_optimizer.put_split", {"record": split_record})
    dispatch("prompt_optimizer.put_family", {"record": family_record})
    pending = store_experiment(family_record, candidate_record)

    binding = pending["evaluationBinding"]
    assert isinstance(binding, dict)
    drifted_binding = recanonicalize_experiment(
        {
            **pending,
            "evaluationBinding": {
                **binding,
                "outcomeContractVersion": "wrong-outcome-contract-v1",
            },
        }
    )
    drifted_evaluator = recanonicalize_experiment(
        {**pending, "evaluatorVersion": "wrong-evaluator-v1"}
    )
    for record in (drifted_binding, drifted_evaluator):
        with pytest.raises(RpcError, match="evaluator_binding_mismatch"):
            dispatch("prompt_optimizer.put_experiment", {"record": record})


def test_prompt_optimizer_bridge_rejects_noncanonical_family_candidate_order(
    isolated_store: PromptOptimizerStore,
) -> None:
    from tests.test_prompt_optimizer_store import (
        candidate as store_candidate,
        family as store_family,
        recanonicalize_family,
        split as store_split,
    )

    split_record = store_split()
    supplementary_id = "candidate-\U00010000"
    bmp_id = "candidate-\ue000"
    noncanonical_ids = [bmp_id, supplementary_id]
    assert noncanonical_ids != sorted(
        noncanonical_ids, key=canonical_string_sort_key
    )
    for candidate_id in noncanonical_ids:
        dispatch(
            "prompt_optimizer.put_candidate",
            {
                "record": store_candidate(
                    candidate_id,
                    split_record=split_record,
                )
            },
        )
    dispatch("prompt_optimizer.put_split", {"record": split_record})
    family_record = store_family(split_record, noncanonical_ids)
    family_record["candidateIds"] = noncanonical_ids
    family_record = recanonicalize_family(family_record)
    with pytest.raises(RpcError, match="candidate_ids_not_canonical"):
        dispatch("prompt_optimizer.put_family", {"record": family_record})


def test_prompt_optimizer_bridge_uses_store_clock_for_run_completion(
    isolated_store: PromptOptimizerStore,
) -> None:
    from tests.test_prompt_optimizer_store import (
        complete_run,
        experiment as store_experiment,
        register,
        run_proposal,
        validation_sample_id,
    )

    split_record, family_record, candidates = register(isolated_store)
    pending = store_experiment(family_record, candidates[0])
    isolated_store.put_experiment(pending)
    isolated_store.put_experiment({**pending, "status": "VALIDATION_RUNNING"})
    claimed = dispatch(
        "prompt_optimizer.claim_run",
        {
            "record": run_proposal(
                str(pending["experimentId"]),
                "VALIDATION",
                "CHAMPION",
                validation_sample_id(split_record),
            ),
            "lease_duration_ms": 60_000,
        },
    )
    assert isinstance(claimed, dict)
    claimed_record = claimed.get("record")
    assert isinstance(claimed_record, dict)
    requested = {
        **complete_run(claimed_record),
        "completedAt": "1900-01-01T00:00:00Z",
    }
    before = datetime.now(timezone.utc)
    stored = dispatch("prompt_optimizer.put_run", {"record": requested})
    after = datetime.now(timezone.utc)
    assert isinstance(stored, dict)
    completed_at = datetime.fromisoformat(
        str(stored["completedAt"]).replace("Z", "+00:00")
    )
    started_at = datetime.fromisoformat(
        str(stored["startedAt"]).replace("Z", "+00:00")
    )
    assert stored["completedAt"] != requested["completedAt"]
    assert started_at <= completed_at
    assert before - timedelta(seconds=1) <= completed_at <= after


def test_prompt_optimizer_bridge_replays_store_semantics_on_direct_writes(
    isolated_store: PromptOptimizerStore,
) -> None:
    from tests.test_prompt_optimizer_store import (
        aggregate_metrics_from_runs,
        candidate as store_candidate,
        complete_partition,
        experiment as store_experiment,
        family as store_family,
        promotion_policy,
        recanonicalize_split,
        register,
        run_proposal,
        split as store_split,
        validation_sample_id,
    )

    overlapping = store_split()
    first = overlapping["validation"]["samples"][0]
    overlapping["validation"]["samples"][1]["eventWindow"] = dict(
        first["eventWindow"]
    )
    with pytest.raises(RpcError, match="sample_windows_overlap"):
        dispatch(
            "prompt_optimizer.put_split",
            {"record": recanonicalize_split(overlapping)},
        )

    split_record = store_split()
    drifted_candidate = {
        **store_candidate("candidate-bridge-drift", split_record=split_record),
        "excludedSampleIdsHash": HASH_A,
    }
    dispatch("prompt_optimizer.put_candidate", {"record": drifted_candidate})
    dispatch("prompt_optimizer.put_split", {"record": split_record})
    with pytest.raises(RpcError, match="training_split_mismatch"):
        dispatch(
            "prompt_optimizer.put_family",
            {
                "record": store_family(
                    split_record, [str(drifted_candidate["candidateId"])]
                )
            },
        )

    family_record = store_family(split_record)
    candidate_record = store_candidate(split_record=split_record)
    invalid_experiment = {
        **store_experiment(family_record, candidate_record, "COMPLETE"),
        "completedAt": None,
    }
    with pytest.raises(RpcError, match="completion_timestamp_invalid"):
        dispatch(
            "prompt_optimizer.put_experiment", {"record": invalid_experiment}
        )
    invalid_run = run_proposal(
        str(store_experiment(family_record, candidate_record)["experimentId"]),
        "VALIDATION",
        "CHAMPION",
        validation_sample_id(split_record),
    )
    invalid_run["retryable"] = True
    with pytest.raises(RpcError, match="retryable_state_invalid"):
        dispatch(
            "prompt_optimizer.claim_run",
            {"record": invalid_run, "lease_duration_ms": 60_000},
        )

    registered_split, registered_family, candidates = register(isolated_store)
    pending = store_experiment(registered_family, candidates[0])
    isolated_store.put_experiment(pending)
    running = {**pending, "status": "VALIDATION_RUNNING"}
    isolated_store.put_experiment(running)
    runs = complete_partition(
        isolated_store,
        running,
        "VALIDATION",
        registered_split["validation"]["samples"],
    )
    validation_complete = store_experiment(
        registered_family,
        candidates[0],
        "VALIDATION_COMPLETE",
        [str(value["runId"]) for value in runs],
    )
    validation_complete["metrics"] = aggregate_metrics_from_runs("VALIDATION", runs)
    isolated_store.put_experiment(validation_complete)
    holdout = {
        **validation_complete,
        "status": "HOLDOUT_RUNNING",
        "holdoutOpenedAt": "2025-04-01T01:00:00Z",
    }
    policy = promotion_policy(registered_split)
    isolated_store.authorized_policy_hashes = frozenset(
        {registered_family["promotionPolicyConfigHash"]}
    )
    with pytest.raises(RpcError, match="holdout_policy_required"):
        dispatch("prompt_optimizer.put_experiment", {"record": holdout})
    stored_holdout = dispatch(
        "prompt_optimizer.put_experiment",
        {"record": holdout, "promotion_policy": policy},
    )
    assert isinstance(stored_holdout, dict)
    assert stored_holdout["experimentId"] == holdout["experimentId"]
    assert stored_holdout["status"] == "HOLDOUT_RUNNING"
    assert stored_holdout["holdoutOpenedAt"] != holdout["holdoutOpenedAt"]
