"""Emit deterministic public Prompt-training projections for cross-repo checks.

This is a contract fixture generator, not a production data path.  It exercises
the real public projection builder with sealed synthetic inputs so the private
Prompt repository can verify its consumer without importing public internals.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mosaic.scorecard import prompt_training_history as training_history  # noqa: E402
from mosaic.scorecard.canonical_json import canonical_hash  # noqa: E402
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS  # noqa: E402


CUTOFF_AT = "2026-08-01T00:00:00+08:00"


def _hash(kind: str, agent_id: str, ordinal: int = 0) -> str:
    return canonical_hash({"kind": kind, "agentId": agent_id, "ordinal": ordinal})


def _record(agent_id: str, ordinal: int) -> dict[str, object]:
    specs = training_history._ROLE_COMPONENT_SPECS[agent_id]
    macro_components = [
        selector
        for _, scorer, selector in specs
        if scorer == "MACRO_COMPONENT" and selector is not None
    ]
    decision_components = [
        selector
        for _, scorer, selector in specs
        if scorer == "DECISION_COMPONENT" and selector is not None
    ]
    component_signals = [
        {
            "component": component,
            "signal": 0.25,
            "effective_confidence": 0.8,
            "componentSignalHash": _hash(component, agent_id, ordinal),
        }
        for component in macro_components
    ]
    return {
        "sampleId": f"conformance-{agent_id}-{ordinal:02d}",
        "agentOutputHash": _hash("agent-output", agent_id, ordinal),
        "outcomeLabelRef": f"outcome://{agent_id}/{ordinal:02d}",
        "outcomeLabelHash": _hash("outcome-label", agent_id, ordinal),
        "asOf": "2026-06-01T00:00:00+08:00",
        "maturedAt": "2026-07-01T00:00:00+08:00",
        "promptBehaviorVersion": "conformance-v1",
        "normalizedScore": 0.25,
        "rawMetrics": {
            "realized_scaled_path": 0.25,
            "direction_metrics": [
                {
                    "selected_role": "PREFERRED",
                    "realized_scaled_path": 0.25,
                    "predicted_tilt": 0.2,
                },
                {
                    "selected_role": "LEAST_PREFERRED",
                    "realized_scaled_path": -0.25,
                    "predicted_tilt": -0.2,
                },
            ],
            "security_leg_metrics": [
                {"side": "PREFERRED", "side_security_utility_delta": 0.2},
                {"side": "LEAST_PREFERRED", "side_security_utility_delta": -0.2},
            ],
            "edge_metrics": [
                {
                    "edge_utility_delta": 0.2,
                    "activation_direction_brier_skill": 0.1,
                    "path_lift_utility_delta": 0.15,
                }
            ],
            "components": [
                {"component_id": component, "utility_delta": 0.2}
                for component in decision_components
            ],
            "output_confidence_null_loss": 0.4,
            "output_confidence_forecast_loss": 0.2,
        },
        "componentSignals": component_signals,
        "supportingAcceptedOutputs": {},
    }


def _experiment(agent_id: str) -> dict[str, object]:
    return {
        "candidateId": f"candidate-{agent_id}",
        "candidatePrivateLineageHash": _hash("private-lineage", agent_id),
        "experimentId": f"experiment-{agent_id}",
        "status": "COMPLETE",
        "evaluatorVersion": "conformance-evaluator-v1",
        "evaluatorConfigHash": _hash("evaluator-config", agent_id),
        "executorAdapterHash": _hash("executor-adapter", agent_id),
        "evaluatorAdapterHash": _hash("evaluator-adapter", agent_id),
        "codeCommit": "a" * 40,
        "pairDeltas": [0.1],
        "failureCaseRefs": [],
        "completedAt": "2026-07-01T00:00:00+00:00",
    }


def build_conformance_bundle() -> dict[str, object]:
    projections: list[dict[str, object]] = []
    with sqlite3.connect(":memory:") as conn:
        for agent_id in OUTCOME_CONTRACTS:
            stage = training_history._target_stage(agent_id)
            sealed_inputs = {
                "target": {
                    "agentId": agent_id,
                    "stage": stage,
                    "cohort": "cohort_default",
                },
                "cutoffAt": CUTOFF_AT,
                "excludedSampleIds": [],
                "records": [_record(agent_id, ordinal) for ordinal in range(30)],
                "validationExperiments": [_experiment(agent_id)],
            }
            with patch.object(
                training_history,
                "_collect_prompt_training_inputs",
                return_value=sealed_inputs,
            ):
                projections.append(
                    training_history.build_prompt_training_projection(
                        conn,
                        agent_id=agent_id,
                        stage=stage,
                        cohort="cohort_default",
                        cutoff_at=CUTOFF_AT,
                    )
                )
    return {
        "schemaVersion": "prompt_training_projection_conformance_bundle_v1",
        "projections": projections,
    }


if __name__ == "__main__":
    print(json.dumps(build_conformance_bundle(), separators=(",", ":"), sort_keys=True))
