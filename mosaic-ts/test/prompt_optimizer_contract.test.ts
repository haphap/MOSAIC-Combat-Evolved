import { describe, expect, it } from "vitest";
import { canonicalJsonHash } from "../src/agents/helpers/canonical_json.js";
import { RUNTIME_AGENT_STAGE_SPECS } from "../src/agents/prompts/runtime_agent_spec.js";
import {
  assertCandidateMatchesSplit,
  assertCandidateMatchesTrainingSnapshot,
  assertTrainingProjectionMatchesSplit,
  buildPromptCandidatePublication,
  DatasetSplitManifestSchema,
  PROMPT_ROLE_COMPONENT_ORDINALS,
  PromptCandidateFamilySchema,
  PromptCandidateSchema,
  PromptExperimentRunSchema,
  PromptExperimentSchema,
  PromptOptimizerTargetSchema,
  PromptPromotionDecisionSchema,
  PromptTrainingProjectionSchema,
  promptCandidateFamilyId,
  promptDatasetPartitionSnapshotHash,
  promptDatasetSampleId,
  promptDatasetSplitId,
  promptExperimentId,
  promptExperimentRunId,
  promptMutationHypothesis,
  promptMutationSummary,
  promptRoleComponentRefs,
  promptSplitExcludedSampleIdsHash,
} from "../src/autoresearch/prompt_optimizer_contract.js";

const HASH = `sha256:${"a".repeat(64)}`;
const OTHER_HASH = `sha256:${"b".repeat(64)}`;
const COMMIT = "c".repeat(40);
const EXECUTION_BEHAVIOR_RELEASE = {
  release_id: `execution-behavior-release:${"d".repeat(64)}`,
  release_hash: HASH,
  archive_ref: `registry/prompt_checks/execution_behavior_releases/${"d".repeat(64)}--${"a".repeat(64)}.json`,
} as const;
const target = { agentId: "china", stage: "agent_run", cohort: "cohort_default" } as const;

function sample(sampleId: string, startAt: string, endAt: string, maturedAt: string) {
  const value = {
    inputRef: `snapshot://${sampleId}`,
    inputHash: HASH,
    outcomeRef: `outcome://${sampleId}`,
    outcomeHash: OTHER_HASH,
    eventWindow: { startAt, endAt },
    maturedAt,
  };
  return { ...value, sampleId: promptDatasetSampleId(value) };
}

function canonicalSplit<T extends ReturnType<typeof splitBody>>(value: T) {
  const withPartitionHashes = {
    ...value,
    training: {
      ...value.training,
      snapshotHash: promptDatasetPartitionSnapshotHash(value.training),
    },
    validation: {
      ...value.validation,
      snapshotHash: promptDatasetPartitionSnapshotHash(value.validation),
    },
    holdout: {
      ...value.holdout,
      snapshotHash: promptDatasetPartitionSnapshotHash(value.holdout),
    },
  };
  return { ...withPartitionHashes, splitId: promptDatasetSplitId(withPartitionHashes) };
}

function splitBody() {
  return {
    schemaVersion: "prompt_dataset_split_v1" as const,
    target,
    trainingProjectionHash: HASH,
    cutoffAt: "2025-01-31T00:00:00Z",
    training: {
      windowStartAt: "2025-01-01T00:00:00Z",
      windowEndAt: "2025-01-31T00:00:00Z",
      samples: [
        sample("train-1", "2025-01-10T00:00:00Z", "2025-01-11T00:00:00Z", "2025-01-20T00:00:00Z"),
      ],
    },
    validation: {
      windowStartAt: "2025-02-01T00:00:00Z",
      windowEndAt: "2025-02-28T00:00:00Z",
      samples: [
        sample(
          "validation-1",
          "2025-02-10T00:00:00Z",
          "2025-02-11T00:00:00Z",
          "2025-02-20T00:00:00Z",
        ),
      ],
    },
    holdout: {
      windowStartAt: "2025-03-01T00:00:00Z",
      windowEndAt: "2025-03-31T00:00:00Z",
      samples: [
        sample("holdout-1", "2025-03-10T00:00:00Z", "2025-03-11T00:00:00Z", "2025-03-20T00:00:00Z"),
      ],
    },
    evaluatorVersion: "agent-outcome-v2",
    createdAt: "2025-04-01T00:00:00Z",
  };
}

function splitManifest() {
  return canonicalSplit(splitBody());
}

function candidate(split = DatasetSplitManifestSchema.parse(splitManifest())) {
  const promptHashes = { zh: HASH, en: OTHER_HASH };
  const mutationCategories = ["CONFLICT_RESOLUTION"] as const;
  return {
    schemaVersion: "prompt_candidate_v1" as const,
    candidateId: "candidate-1",
    parentId: "champion-1",
    parentPromptCommit: COMMIT,
    parentPromptHashes: { zh: OTHER_HASH, en: HASH },
    target,
    promptRefs: { zh: "private://candidate-1.zh", en: "private://candidate-1.en" },
    promptHashes,
    trainingProjectionHash: split.trainingProjectionHash,
    excludedSampleIdsHash: promptSplitExcludedSampleIdsHash(split),
    mutatorConfigHash: HASH,
    mutatorCommit: COMMIT,
    mutationCategories,
    mutationSummary: promptMutationSummary(mutationCategories),
    hypothesis: promptMutationHypothesis(mutationCategories),
    behaviorContractHash: HASH,
    privateLineageHash: HASH,
    privateStateArtifactHash: HASH,
    createdAt: "2025-04-01T00:00:00Z",
  };
}

describe("prompt optimizer public contracts", () => {
  it("covers all 27 Agent-owned champions and rejects the shared CIO proposal stage", () => {
    expect(new Set(RUNTIME_AGENT_STAGE_SPECS.map((row) => row.agent)).size).toBe(27);
    expect(RUNTIME_AGENT_STAGE_SPECS).toHaveLength(28);
    for (const row of RUNTIME_AGENT_STAGE_SPECS.filter(
      (value) => !(value.agent === "cio" && value.stage === "cio_proposal"),
    )) {
      expect(
        PromptOptimizerTargetSchema.parse({
          agentId: row.agent,
          stage: row.stage,
          cohort: "cohort_default",
        }),
      ).toBeDefined();
    }
    expect(() =>
      PromptOptimizerTargetSchema.parse({
        agentId: "cio",
        stage: "cio_proposal",
        cohort: "cohort_default",
      }),
    ).toThrow(/shares the cio_final Prompt champion/);
  });

  it("rejects a stage owned by a different Agent", () => {
    expect(() =>
      PromptOptimizerTargetSchema.parse({
        agentId: "china",
        stage: "cio_final",
        cohort: "cohort_default",
      }),
    ).toThrow(/does not belong/);
  });

  it("accepts the minimal public objects and rejects prompt bodies", () => {
    expect(PromptCandidateSchema.parse(candidate())).toBeDefined();
    expect(
      PromptCandidateSchema.safeParse({ ...candidate(), candidateId: " candidate-1 " }).success,
    ).toBe(false);
    for (const suffix of ["\n", "\r", "\r\n", "\u2028", "\uFEFF"]) {
      expect(
        PromptCandidateSchema.safeParse({
          ...candidate(),
          candidateId: `candidate-1${suffix}`,
        }).success,
      ).toBe(false);
    }
    expect(
      PromptCandidateSchema.safeParse({
        ...candidate(),
        promptRefs: { ...candidate().promptRefs, zh: " private://candidate-1.zh " },
      }).success,
    ).toBe(false);
    expect(() =>
      PromptCandidateSchema.parse({ ...candidate(), zh_prompt: "private body" }),
    ).toThrow();
    expect(() =>
      PromptCandidateSchema.parse({
        ...candidate(),
        deterministic_policy: { "cro.stop_loss_pct": -0.2 },
      }),
    ).toThrow();
    expect(() =>
      PromptCandidateSchema.parse({
        ...candidate(),
        behaviorContractHash: "private verifier rationale must not cross",
      }),
    ).toThrow();
    const split = DatasetSplitManifestSchema.parse(splitManifest());
    const parsedCandidate = PromptCandidateSchema.parse(candidate(split));
    const publication = buildPromptCandidatePublication({
      candidate: parsedCandidate,
      promptSourceId: "private-prompts",
      candidatePromptCommit: "d".repeat(40),
    });
    expect(publication.publicationHash).toMatch(/^sha256:/);
    const familyBody = {
      schemaVersion: "prompt_candidate_family_v2" as const,
      target,
      championReleaseId: "champion-1",
      championPromptSourceId: "private-prompts",
      championPromptCommit: COMMIT,
      championPromptRefs: { zh: "private://champion.zh", en: "private://champion.en" },
      championPromptHashes: { zh: OTHER_HASH, en: HASH },
      datasetSplitId: split.splitId,
      datasetSplitManifestHash: canonicalJsonHash(split),
      promotionPolicyVersion: "policy-v1",
      promotionPolicyConfigHash: HASH,
      candidateIds: [parsedCandidate.candidateId],
      createdAt: "2025-04-01T00:00:00Z",
    };
    const family = PromptCandidateFamilySchema.parse({
      ...familyBody,
      familyId: promptCandidateFamilyId(familyBody),
    });
    expect(family).toBeDefined();
    const paddedFamilyBody = { ...familyBody, championReleaseId: " champion-1 " };
    expect(
      PromptCandidateFamilySchema.safeParse({
        ...paddedFamilyBody,
        familyId: promptCandidateFamilyId(paddedFamilyBody),
      }).success,
    ).toBe(false);
    const experimentBody = {
      schemaVersion: "prompt_experiment_v2" as const,
      familyId: family.familyId,
      candidateId: parsedCandidate.candidateId,
      championId: "champion-1",
      target,
      championPromptCommit: COMMIT,
      championPromptSourceId: family.championPromptSourceId,
      championPromptRefs: family.championPromptRefs,
      championPromptHashes: { zh: OTHER_HASH, en: HASH },
      candidatePromptRefs: parsedCandidate.promptRefs,
      candidatePromptHashes: parsedCandidate.promptHashes,
      candidatePromptSourceId: publication.promptSourceId,
      candidatePromptCommit: publication.candidatePromptCommit,
      candidatePublicationHash: publication.publicationHash,
      datasetSplitId: split.splitId,
      datasetSplitManifestHash: canonicalJsonHash(split),
      promotionPolicyVersion: family.promotionPolicyVersion,
      promotionPolicyConfigHash: family.promotionPolicyConfigHash,
      modelConfigHash: HASH,
      toolConfigHash: HASH,
      componentCalibrationSnapshotHash: HASH,
      darwinianUsageSnapshotHash: OTHER_HASH,
      executorAdapterHash: HASH,
      evaluatorAdapterHash: OTHER_HASH,
      evaluationBinding: {
        evaluationObject: "AcceptedMacroTransmission",
        evaluationObjectSchemaVersion: "accepted_macro_transmission_v2",
        primaryLabelId: "china_macro_transmission_a_share_path_5d",
        scoringContractVersion: "score_china_macro_transmission_a_share_path_5d_v1",
        outcomeContractVersion: "macro_transmission_outcome_v2",
      },
      evaluatorVersion: "agent-outcome-v2",
      evaluatorConfigHash: HASH,
      codeCommit: COMMIT,
      executionBehaviorRelease: EXECUTION_BEHAVIOR_RELEASE,
      repeatSeeds: [1, 2],
      runIds: [],
      metrics: {},
      tailFailureCaseRefs: [],
      status: "PENDING" as const,
      holdoutOpenedAt: null,
      createdAt: "2025-04-01T00:00:00Z",
      completedAt: null,
    };
    expect(
      PromptExperimentSchema.parse({
        ...experimentBody,
        experimentId: promptExperimentId(experimentBody),
      }),
    ).toBeDefined();
    const paddedExperimentBody = { ...experimentBody, championId: " champion-1 " };
    expect(
      PromptExperimentSchema.safeParse({
        ...paddedExperimentBody,
        experimentId: promptExperimentId(paddedExperimentBody),
      }).success,
    ).toBe(false);
    expect(
      PromptPromotionDecisionSchema.parse({
        schemaVersion: "prompt_promotion_decision_v1",
        decisionId: "decision-1",
        experimentId: "experiment-1",
        familyId: "family-1",
        candidateId: "candidate-1",
        policyVersion: "policy-v1",
        policyConfigHash: HASH,
        decision: "REJECTED",
        reasons: ["validation_delta_below_threshold"],
        metricSummary: { paired_delta: 0 },
        evidenceHash: HASH,
        decidedAt: "2025-04-01T00:00:00Z",
      }),
    ).toBeDefined();
  });

  it("exposes only a strict training projection to KNOT", () => {
    const reservedSplit = DatasetSplitManifestSchema.parse(splitManifest());
    const trainingBody = {
      schemaVersion: "prompt_training_projection_v1",
      target,
      projectionId: "training-1",
      datasetSnapshotHash: OTHER_HASH,
      excludedSampleIdsHash: promptSplitExcludedSampleIdsHash(reservedSplit),
      cutoffAt: "2025-01-31T00:00:00Z",
      outcomeContract: {
        evaluationObject: "AcceptedMacroTransmission",
        outcomeContractVersion: "macro_transmission_outcome_v2",
        primaryLabelId: "china_macro_transmission_a_share_path_5d",
        maturityHorizon: "TRADING_DAYS_5",
        maturityTradingDays: 5,
      },
      evaluator: {
        version: "score_china_macro_transmission_a_share_path_5d_v1",
        configHash: HASH,
        implementationHash: HASH,
        executorAdapterHash: HASH,
        evaluatorAdapterHash: OTHER_HASH,
      },
      matureSampleCount: 30,
      scoreSummary: { mean: 0.1 },
      failureCategoryCounts: { missing_counter_evidence: 4 },
      tailFailureCaseRefs: ["failure://train-1"],
      evidenceGapSummaries: ["Counter-evidence was not checked before conclusion."],
      directComponents: Array.from(
        { length: 6 },
        (_, ordinal) =>
          ({
            componentRef: `role_component_v1:china:${ordinal.toString().padStart(3, "0")}`,
            directMatureSampleCount: 30,
            meanScore: 0.1 - ordinal * 0.01,
            lowerTailScore: -0.2 - ordinal * 0.01,
            failureCategoryCounts: { missing_counter_evidence: 4 },
          }) as const,
      ),
      controlledExperiments: [
        {
          candidateId: "candidate-history-1",
          candidatePrivateLineageHash: HASH,
          experimentId: "experiment-history-1",
          status: "COMPLETE",
          evaluatorVersion: "agent-outcome-v2",
          evaluatorConfigHash: HASH,
          executorAdapterHash: HASH,
          evaluatorAdapterHash: OTHER_HASH,
          codeCommit: COMMIT,
          pairDeltas: [0.1, -0.05],
          failureCaseRefs: [],
          completedAt: "2025-01-20T00:00:00Z",
        },
      ],
    } as const;
    const training = PromptTrainingProjectionSchema.parse({
      ...trainingBody,
      projectionHash: canonicalJsonHash(trainingBody),
    });
    const matchingSplit = DatasetSplitManifestSchema.parse(
      canonicalSplit({
        ...splitBody(),
        training: reservedSplit.training,
        validation: reservedSplit.validation,
        holdout: reservedSplit.holdout,
        trainingProjectionHash: training.projectionHash,
      }),
    );
    expect(() => assertTrainingProjectionMatchesSplit(training, matchingSplit)).not.toThrow();
    expect(() =>
      assertTrainingProjectionMatchesSplit(training, {
        ...matchingSplit,
        trainingProjectionHash: OTHER_HASH,
      }),
    ).toThrow("training_projection_dataset_split_mismatch");
    const boundCandidate = PromptCandidateSchema.parse({
      ...candidate(matchingSplit),
      trainingProjectionHash: training.projectionHash,
    });
    assertCandidateMatchesTrainingSnapshot(boundCandidate, training);
    const coldComponents = trainingBody.directComponents.map((component) => ({
      ...component,
      directMatureSampleCount: 29,
    }));
    const coldBody = {
      ...trainingBody,
      matureSampleCount: 29,
      directComponents: coldComponents,
    };
    const coldTraining = PromptTrainingProjectionSchema.parse({
      ...coldBody,
      projectionHash: canonicalJsonHash(coldBody),
    });
    expect(() => assertCandidateMatchesTrainingSnapshot(boundCandidate, coldTraining)).toThrow(
      "candidate_training_sample_count_insufficient",
    );
    expect(() =>
      PromptTrainingProjectionSchema.parse({ ...training, validationSnapshotHash: OTHER_HASH }),
    ).toThrow();
    expect(() =>
      assertCandidateMatchesTrainingSnapshot(
        { ...boundCandidate, trainingProjectionHash: OTHER_HASH },
        training,
      ),
    ).toThrow("candidate_training_snapshot_mismatch");
    expect(() =>
      PromptTrainingProjectionSchema.parse({
        ...training,
        directComponents: [{ ...training.directComponents[0], directMatureSampleCount: 31 }],
      }),
    ).toThrow(/complete mature sample set/);
    expect(() =>
      PromptTrainingProjectionSchema.parse({
        ...training,
        evaluator: { ...training.evaluator, version: "changed-evaluator" },
      }),
    ).toThrow(/hash must bind/);
    const wrongComponentBody = {
      ...trainingBody,
      directComponents: [
        { ...trainingBody.directComponents[0], componentRef: "role_component_v1:cio:001" },
      ],
    };
    expect(() =>
      PromptTrainingProjectionSchema.parse({
        ...wrongComponentBody,
        projectionHash: canonicalJsonHash(wrongComponentBody),
      }),
    ).toThrow(/must belong to the projection target/);
    const lastDirectComponent = training.directComponents.at(-1);
    if (!lastDirectComponent) throw new Error("missing direct component fixture");
    for (const directComponents of [
      training.directComponents.slice(0, -1),
      [
        ...training.directComponents.slice(0, -1),
        { ...lastDirectComponent, componentRef: "role_component_v1:china:999" },
      ],
      [...training.directComponents].reverse(),
    ]) {
      const invalidBody = { ...trainingBody, directComponents };
      expect(() =>
        PromptTrainingProjectionSchema.parse({
          ...invalidBody,
          projectionHash: canonicalJsonHash(invalidBody),
        }),
      ).toThrow(/complete ordered role roster/);
    }
  });

  it("defines one exact public role-component roster for every Agent", () => {
    const agentIds = new Set(RUNTIME_AGENT_STAGE_SPECS.map((row) => row.agent));
    const rosterAgentIds = Object.keys(PROMPT_ROLE_COMPONENT_ORDINALS) as Array<
      keyof typeof PROMPT_ROLE_COMPONENT_ORDINALS
    >;
    expect(new Set(rosterAgentIds)).toEqual(agentIds);
    for (const agentId of rosterAgentIds) {
      expect(promptRoleComponentRefs(agentId)).toEqual(
        PROMPT_ROLE_COMPONENT_ORDINALS[agentId].map(
          (ordinal) => `role_component_v1:${agentId}:${ordinal.toString().padStart(3, "0")}`,
        ),
      );
    }
  });

  it("binds sample and split identities while rejecting overlap or future leakage", () => {
    expect(DatasetSplitManifestSchema.parse(splitManifest())).toBeDefined();
    expect(() =>
      DatasetSplitManifestSchema.parse({ ...splitManifest(), splitId: "split-alias" }),
    ).toThrow(/derived from the immutable split definition/);
    const aliasedSample = splitManifest();
    const firstHoldout = aliasedSample.holdout.samples[0];
    if (!firstHoldout) throw new Error("missing holdout sample");
    aliasedSample.holdout.samples[0] = { ...firstHoldout, sampleId: "sample-alias" };
    expect(() => DatasetSplitManifestSchema.parse(aliasedSample)).toThrow(
      /derived from the immutable sample content/,
    );
    const aliasedPartition = splitManifest();
    expect(() =>
      DatasetSplitManifestSchema.parse({
        ...aliasedPartition,
        training: { ...aliasedPartition.training, snapshotId: "training-alias" },
      }),
    ).toThrow();

    const createdBeforeCutoff = splitBody();
    createdBeforeCutoff.createdAt = "2025-01-01T00:00:00Z";
    expect(() => DatasetSplitManifestSchema.parse(canonicalSplit(createdBeforeCutoff))).toThrow(
      /before its training cutoff/,
    );

    const intervalOverlap = splitBody();
    intervalOverlap.validation.samples.push(
      sample(
        "validation-2",
        "2025-02-10T12:00:00Z",
        "2025-02-11T12:00:00Z",
        "2025-02-20T00:00:00Z",
      ),
    );
    expect(() => DatasetSplitManifestSchema.parse(canonicalSplit(intervalOverlap))).toThrow(
      /cannot overlap/,
    );

    const touching = splitBody();
    touching.validation.samples.push(
      sample(
        "validation-2",
        "2025-02-11T00:00:00Z",
        "2025-02-12T00:00:00Z",
        "2025-02-20T00:00:00Z",
      ),
    );
    expect(DatasetSplitManifestSchema.parse(canonicalSplit(touching))).toBeDefined();

    const future = splitBody();
    const futureSample = future.holdout.samples.at(0);
    if (!futureSample) throw new Error("missing future fixture sample");
    future.holdout.samples[0] = {
      ...futureSample,
      maturedAt: "2025-05-01T00:00:00Z",
    };
    future.holdout.samples[0].sampleId = promptDatasetSampleId(future.holdout.samples[0]);
    expect(() => DatasetSplitManifestSchema.parse(canonicalSplit(future))).toThrow(/immature/);
  });

  it("orders timestamp offsets by instant rather than source spelling", () => {
    const value = splitBody();
    value.training.samples[0] = sample(
      "train-1",
      "2025-01-11T00:00:00-12:00",
      "2025-01-11T01:00:00-12:00",
      "2025-01-11T23:00:00+14:00",
    );
    expect(() => DatasetSplitManifestSchema.parse(canonicalSplit(value))).toThrow(/mature before/);
  });

  it("binds Candidate training identity to the frozen split", () => {
    const parsedCandidate = PromptCandidateSchema.parse(candidate());
    const parsedSplit = DatasetSplitManifestSchema.parse(splitManifest());
    expect(() => assertCandidateMatchesSplit(parsedCandidate, parsedSplit)).not.toThrow();
    expect(() =>
      assertCandidateMatchesSplit(
        { ...parsedCandidate, trainingProjectionHash: OTHER_HASH },
        parsedSplit,
      ),
    ).toThrow("candidate_dataset_split_mismatch");
    expect(() =>
      assertCandidateMatchesSplit(
        { ...parsedCandidate, excludedSampleIdsHash: OTHER_HASH },
        parsedSplit,
      ),
    ).toThrow("candidate_dataset_split_mismatch");
  });

  it("requires complete runs to carry one normalized Agent-specific score", () => {
    const base = {
      schemaVersion: "prompt_experiment_run_v1" as const,
      experimentId: "experiment-1",
      partition: "VALIDATION" as const,
      side: "CHAMPION" as const,
      sampleId: "validation-1",
      seed: 1,
      status: "COMPLETE" as const,
      leaseOwner: "worker-1",
      leaseExpiresAt: "2025-04-01T00:05:00Z",
      attempt: 1,
      retryable: false,
      attemptFailureCodes: [],
      agentOutputRef: "accepted://output-1",
      metrics: { normalized_score: 0.2 },
      failureCaseRefs: [],
      traceRef: null,
      effectiveInputHash: HASH,
      errorCode: null,
      startedAt: "2025-04-01T00:00:00Z",
      completedAt: "2025-04-01T00:01:00Z",
    };
    const canonical = { ...base, runId: promptExperimentRunId(base) };
    expect(PromptExperimentRunSchema.parse(canonical)).toBeDefined();
    expect(() => PromptExperimentRunSchema.parse({ ...canonical, metrics: {} })).toThrow(/score/);
    expect(() => PromptExperimentRunSchema.parse({ ...canonical, runId: "run-alias" })).toThrow(
      /immutable run coordinates/,
    );
  });
});
