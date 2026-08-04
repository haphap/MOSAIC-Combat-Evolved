import { describe, expect, it, vi } from "vitest";
import { canonicalJsonHash } from "../src/agents/helpers/canonical_json.js";
import { PromptTrainingHistorySchema } from "../src/autoresearch/prompt_training_history.js";
import { BridgeApi, type BridgeClient } from "../src/bridge/index.js";
import { assertPrivateCandidateMatchesRequest } from "../src/cli/commands/autoresearch.js";

const HASH = `sha256:${"a".repeat(64)}`;

function history(overrides: Record<string, unknown> = {}) {
  const body = {
    schemaVersion: "prompt_training_history_v1" as const,
    exporterVersion: "prompt_training_history_exporter_v1",
    target: { agentId: "china", stage: "agent_run", cohort: "cohort_default" },
    cutoffAt: "2025-01-31T00:00:00Z",
    outcomeContractVersion: "china-outcome-v2",
    metricFamily: "MACRO",
    primaryLabelId: "macro_path_5d",
    excludedSampleIds: ["validation-1", "holdout-1"],
    records: [
      {
        sampleId: "training-1",
        agentOutputRef: "accepted-1",
        agentOutputHash: HASH,
        outcomeLabelRef: "outcome-1",
        outcomeLabelHash: HASH,
        asOf: "2025-01-01",
        maturedAt: "2025-01-10T00:00:00Z",
        promptBehaviorVersion: "china-prompt-v2",
        normalizedScore: 0.2,
        rawMetrics: { realized_scaled_path: 0.1 },
        componentSignals: [],
        supportingAcceptedOutputs: {},
      },
    ],
    validationExperiments: [],
    ...overrides,
  };
  return { ...body, historyHash: canonicalJsonHash(body) };
}

describe("Prompt training history transport", () => {
  it("accepts a hash-bound PIT training-only projection", () => {
    const parsed = PromptTrainingHistorySchema.parse(history());
    expect(parsed.records[0]?.asOf).toBe("2025-01-01");
  });

  it("rejects holdout fields, reserved overlap, future data, and hash drift", () => {
    expect(() =>
      PromptTrainingHistorySchema.parse(history({ holdoutSamples: ["forbidden"] })),
    ).toThrow();
    expect(() =>
      PromptTrainingHistorySchema.parse(history({ excludedSampleIds: ["training-1"] })),
    ).toThrow(/training sample overlap/);
    const futureRecords = history().records.map((record) => ({
      ...record,
      maturedAt: "2025-02-01T00:00:00Z",
    }));
    expect(() => PromptTrainingHistorySchema.parse(history({ records: futureRecords }))).toThrow(
      /future mature sample/,
    );
    expect(() => PromptTrainingHistorySchema.parse({ ...history(), historyHash: HASH })).toThrow(
      /history hash mismatch/,
    );
    expect(() =>
      PromptTrainingHistorySchema.parse(
        history({ exporterVersion: "prompt_training_history_exporter_v0" }),
      ),
    ).toThrow();
  });

  it("accepts only internally consistent validation pairs completed by the cutoff", () => {
    const experiment = {
      candidateId: "candidate-1",
      candidatePrivateLineageHash: HASH,
      experimentId: "experiment-1",
      evaluatorVersion: "evaluator-v1",
      evaluatorConfigHash: HASH,
      codeCommit: "b".repeat(40),
      validationPairCount: 2,
      validationCandidateMean: 0.6,
      validationChampionMean: 0.4,
      validationPairedDelta: 0.2,
      validationPairDeltas: [0.1, 0.3],
      validationFailureCaseRefs: [],
      validationCompletedAt: "2025-01-20T00:00:00Z",
    };
    expect(
      PromptTrainingHistorySchema.parse(history({ validationExperiments: [experiment] }))
        .validationExperiments,
    ).toHaveLength(1);
    expect(() =>
      PromptTrainingHistorySchema.parse(
        history({
          validationExperiments: [{ ...experiment, validationPairDeltas: [0.1, 0.2] }],
        }),
      ),
    ).toThrow(/validation aggregate mismatch/);
    expect(() =>
      PromptTrainingHistorySchema.parse(
        history({
          validationExperiments: [{ ...experiment, validationCompletedAt: "2025-02-01T00:00:00Z" }],
        }),
      ),
    ).toThrow(/PIT mismatch/);
  });

  it("validates the bridge response before Candidate generation can consume it", async () => {
    const call = vi.fn(async () => ({ history: history() }));
    const api = new BridgeApi({ call } as unknown as BridgeClient);
    await expect(
      api.promptOptimizerTrainingHistory({
        agent_id: "china",
        stage: "agent_run",
        cohort: "cohort_default",
        cutoff_at: "2025-01-31T00:00:00Z",
      }),
    ).resolves.toMatchObject({ schemaVersion: "prompt_training_history_v1" });

    call.mockResolvedValueOnce({ history: { ...history(), historyHash: HASH } });
    await expect(
      api.promptOptimizerTrainingHistory({
        agent_id: "china",
        stage: "agent_run",
        cohort: "cohort_default",
        cutoff_at: "2025-01-31T00:00:00Z",
      }),
    ).rejects.toThrow(/history hash mismatch/);
  });

  it("binds a private Candidate response to the exact public generation request", () => {
    const request = {
      parentId: "champion-1",
      parentPromptCommit: "b".repeat(40),
      target: { agentId: "china" as const, stage: "agent_run" as const, cohort: "cohort_default" },
      promptRefs: { zh: "private/china.zh.md", en: "private/china.en.md" },
      cutoffAt: "2025-01-31T00:00:00Z",
      excludedSampleIds: ["validation-1", "holdout-1"],
      mutatorConfigHash: HASH,
      mutatorCommit: "c".repeat(40),
      createdAt: "2025-02-01T00:00:00Z",
    };
    const candidate = {
      schemaVersion: "prompt_candidate_v1" as const,
      candidateId: "candidate-1",
      parentId: request.parentId,
      parentPromptCommit: request.parentPromptCommit,
      parentPromptHashes: { zh: HASH, en: HASH },
      target: request.target,
      promptRefs: request.promptRefs,
      promptHashes: { zh: HASH, en: HASH },
      trainingSnapshotId: "training-1",
      trainingSnapshotHash: HASH,
      excludedSampleIdsHash: canonicalJsonHash(["holdout-1", "validation-1"]),
      mutatorConfigHash: request.mutatorConfigHash,
      mutatorCommit: request.mutatorCommit,
      mutationCategories: ["EVIDENCE_PRIORITY" as const],
      mutationSummary: "Behavior focus: EVIDENCE_PRIORITY.",
      hypothesis:
        "Preregistered hypothesis: EVIDENCE_PRIORITY improves the frozen Agent outcome score.",
      alignmentVerifierVersion: "alignment-v1",
      behaviorAlignmentHash: HASH,
      behaviorContractHash: HASH,
      privateLineageHash: HASH,
      createdAt: request.createdAt,
    };
    expect(() => assertPrivateCandidateMatchesRequest(candidate, request)).not.toThrow();
    expect(() =>
      assertPrivateCandidateMatchesRequest(
        { ...candidate, target: { ...candidate.target, cohort: "cohort_bull_2007" } },
        request,
      ),
    ).toThrow(/request binding mismatch/);
    expect(() =>
      assertPrivateCandidateMatchesRequest({ ...candidate, excludedSampleIdsHash: HASH }, request),
    ).toThrow(/request binding mismatch/);
  });
});
