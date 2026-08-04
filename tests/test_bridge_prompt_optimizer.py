from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mosaic.bridge.handlers import prompt_optimizer
from mosaic.bridge.protocol import RpcError
from mosaic.bridge.registry import all_methods, get_handler
from mosaic.scorecard.prompt_optimizer_store import PromptOptimizerStore


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def candidate() -> dict[str, object]:
    prompt_hashes = {"zh": HASH_A, "en": HASH_B}
    alignment = {
        "alignmentVerifierVersion": "bilingual-alignment-v1",
        "promptHashes": prompt_hashes,
    }
    alignment_hash = "sha256:" + hashlib.sha256(
        json.dumps(alignment, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
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
        "trainingSnapshotId": "training-bridge",
        "trainingSnapshotHash": HASH_A,
        "mutatorConfigHash": HASH_B,
        "mutatorCommit": "c" * 40,
        "mutationCategories": ["EVIDENCE_PRIORITY"],
        "mutationSummary": "Behavior focus: EVIDENCE_PRIORITY.",
        "hypothesis": (
            "Preregistered hypothesis: EVIDENCE_PRIORITY improves the frozen Agent outcome score."
        ),
        "alignmentVerifierVersion": "bilingual-alignment-v1",
        "behaviorAlignmentHash": alignment_hash,
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
        "prompt_optimizer.get_decision",
        "prompt_optimizer.get_experiment",
        "prompt_optimizer.list_runs",
        "prompt_optimizer.latest_summary",
        "prompt_optimizer.put_candidate",
        "prompt_optimizer.put_family",
        "prompt_optimizer.put_split",
        "prompt_optimizer.put_decision",
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
        "decision": None,
        "release": None,
    }


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
