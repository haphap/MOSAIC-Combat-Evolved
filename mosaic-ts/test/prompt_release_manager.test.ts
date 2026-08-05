import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { canonicalJsonHash } from "../src/agents/helpers/canonical_json.js";
import { releasePromptPairHash } from "../src/agents/prompts/prompt_release_contract.js";
import type { RuntimeAgentSpec } from "../src/agents/prompts/runtime_agent_spec.js";
import { immutablePromptContractHash } from "../src/autoresearch/execution_behavior_release.js";
import {
  buildPromptCandidatePublication,
  type PromptCandidate,
  type PromptPromotionDecision,
  promptMutationHypothesis,
  promptMutationSummary,
} from "../src/autoresearch/prompt_optimizer_contract.js";
import {
  buildPromptReleaseCanaryAssignmentEvent,
  buildPromptReleaseCanarySloArtifact,
  type PromptReleaseCanaryEvent,
  PromptReleaseCanaryEventJournal,
  stageSnapshotHashesHash,
} from "../src/autoresearch/prompt_release_canary_slo.js";
import {
  activatePromptRelease,
  buildPromptReleaseBaselineManifest,
  provisionPromptReleaseBaseline,
  rollbackPromptRelease,
  stagePromptRelease,
  startPromptReleaseCanary,
} from "../src/autoresearch/prompt_release_manager.js";
import { ActivePromptReleaseRegistry } from "../src/autoresearch/release_registry.js";

const HASH = `sha256:${"1".repeat(64)}`;
const EXECUTION_RELEASE_ID = `execution-behavior-release:${"2".repeat(64)}`;
const EXECUTION_RELEASE_REF = `registry/prompt_checks/execution_behavior_releases/${"2".repeat(64)}--${"1".repeat(64)}.json`;
const executionReleaseEnvironment = (codeCommit: string) => ({
  codeCommit,
  executionBehaviorRelease: {
    release_id: EXECUTION_RELEASE_ID,
    release_hash: HASH,
    archive_ref: EXECUTION_RELEASE_REF,
  },
});
const PROMPT_PATHS = {
  zh: "prompts/mosaic/cohort_default/macro/central_bank.zh.md",
  en: "prompts/mosaic/cohort_default/macro/central_bank.en.md",
};
const SPEC: RuntimeAgentSpec = {
  agent: "central_bank",
  layer: "macro",
  promptIrAgentId: "macro.central_bank",
  fieldNames: ["signal"],
  requiredTools: [],
  stages: [
    {
      stage: "agent_run",
      enablement: "enabled",
      outputSchemaRef: "macro.central_bank.output.v1",
      outputSchemaFields: ["signal"],
      maxRepairAttempts: 3,
      requiredSourceIds: [],
      producedSourceIds: ["upstream_agent_outputs"],
    },
  ],
};
const BEHAVIOR_TARGET_CONTRACT = {
  target: { agentId: "central_bank", stage: "agent_run" },
  role_objective: "Assess the PBOC reaction function and liquidity stance.",
  required_facets: [
    {
      id: "policy_stance",
      purpose: "Assess policy stance.",
      evaluation_mode: "DIRECT_OUTCOME",
      allowed_mutations: ["EVIDENCE_PRIORITY"],
    },
  ],
  protected_policy_ids: ["contract.role_tools_schema"],
  comparison_universe: [],
  evaluation: {
    evaluation_object: "AcceptedMacroTransmission",
    primary_label_id: "central_bank_policy_path",
    maturity_horizon: "TRADING_DAYS_5",
    maturity_trading_days: 5,
  },
};
const BEHAVIOR_CONTRACT_ARTIFACT = {
  schema_version: "prompt_behavior_contract_v1",
  contracts: [BEHAVIOR_TARGET_CONTRACT],
};
const roots: string[] = [];

afterEach(() => {
  delete process.env.MOSAIC_PROMPT_RELEASE_AUTHORIZED_OPERATORS;
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function initRepo(files: Record<string, string>): { root: string; commit: string } {
  const root = mkdtempSync(join(tmpdir(), "mosaic-release-manager-"));
  roots.push(root);
  execFileSync("git", ["init", "-q", root]);
  for (const [path, content] of Object.entries(files)) {
    const absolute = join(root, path);
    mkdirSync(dirname(absolute), { recursive: true });
    writeFileSync(absolute, content, "utf-8");
  }
  execFileSync("git", ["-C", root, "add", "."]);
  execFileSync("git", [
    "-C",
    root,
    "-c",
    "user.name=Codex Test",
    "-c",
    "user.email=codex@example.invalid",
    "commit",
    "-qm",
    "fixture",
  ]);
  return {
    root,
    commit: execFileSync("git", ["-C", root, "rev-parse", "HEAD"], {
      encoding: "utf-8",
    }).trim(),
  };
}

function prompt(language: "zh" | "en", behavior: string): string {
  return [
    language === "zh" ? "# 央行" : "# Central bank",
    "",
    "<!-- cohort-behavior:start -->",
    behavior,
    "<!-- cohort-behavior:end -->",
    "",
    language === "zh" ? "## 不可变合同" : "## Immutable contract",
    language === "zh" ? "仅输出规定结构。" : "Return only the required structure.",
  ].join("\n");
}

function commitCandidate(
  repo: { root: string; commit: string },
  value: PromptCandidate,
  promptFiles: Record<string, string>,
  options: { privateLineage?: unknown; extraFiles?: Record<string, string> } = {},
): string {
  for (const [path, content] of Object.entries(promptFiles)) {
    writeFileSync(join(repo.root, path), content, "utf8");
  }
  const record = join(repo.root, `registry/prompt_candidates_v2/${value.candidateId}.json`);
  const privateLineage = join(
    repo.root,
    `registry/prompt_candidate_private_v1/${value.candidateId}.json`,
  );
  const privateState = join(
    repo.root,
    `registry/prompt_parameter_states_v1/${value.target.cohort}/${value.target.stage}/${value.target.agentId}.json`,
  );
  mkdirSync(dirname(record), { recursive: true });
  mkdirSync(dirname(privateLineage), { recursive: true });
  mkdirSync(dirname(privateState), { recursive: true });
  writeFileSync(record, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  writeFileSync(
    privateLineage,
    `${JSON.stringify(options.privateLineage ?? privateLineageArtifact(value), null, 2)}\n`,
    "utf8",
  );
  writeFileSync(
    privateState,
    `${JSON.stringify(privateStateArtifact(value.candidateId), null, 2)}\n`,
    "utf8",
  );
  for (const [path, content] of Object.entries(options.extraFiles ?? {})) {
    const absolute = join(repo.root, path);
    mkdirSync(dirname(absolute), { recursive: true });
    writeFileSync(absolute, content, "utf8");
  }
  const bootstrapRelease = join(
    repo.root,
    "registry/knot/prompt_parameter_bootstrap_release_v1.json",
  );
  mkdirSync(dirname(bootstrapRelease), { recursive: true });
  writeFileSync(
    bootstrapRelease,
    `${JSON.stringify({ candidateId: value.candidateId }, null, 2)}\n`,
    "utf8",
  );
  execFileSync("git", ["-C", repo.root, "add", "."]);
  execFileSync("git", [
    "-C",
    repo.root,
    "-c",
    "user.name=Codex Test",
    "-c",
    "user.email=codex@example.invalid",
    "commit",
    "-qm",
    value.candidateId,
  ]);
  return execFileSync("git", ["-C", repo.root, "rev-parse", "HEAD"], {
    encoding: "utf8",
  }).trim();
}

function privateStateArtifact(candidateId: string) {
  return { schemaVersion: "opaque_private_state_test_v1", candidateId };
}

function privateLineageBody(value: Omit<PromptCandidate, "privateLineageHash">) {
  return {
    schemaVersion: "private_prompt_candidate_parameter_lineage_v1" as const,
    parentId: value.parentId,
    parentPromptCommit: value.parentPromptCommit,
    target: value.target,
    behaviorContractHash: value.behaviorContractHash,
    trainingProjectionHash: value.trainingProjectionHash,
    promptHashes: value.promptHashes,
    mutatorConfigHash: value.mutatorConfigHash,
    mutatorCommit: value.mutatorCommit,
  };
}

function privateLineageArtifact(value: PromptCandidate) {
  const { privateLineageHash: _privateLineageHash, ...withoutLineageHash } = value;
  return {
    ...privateLineageBody(withoutLineageHash),
    candidateId: value.candidateId,
    privateLineageHash: value.privateLineageHash,
  };
}

function privateStateAtCommit(repo: string, commit: string, value: PromptCandidate): unknown {
  const ref =
    `registry/prompt_parameter_states_v1/${value.target.cohort}/` +
    `${value.target.stage}/${value.target.agentId}.json`;
  return JSON.parse(
    execFileSync("git", ["-C", repo, "show", `${commit}:${ref}`], { encoding: "utf8" }),
  );
}

function sha256(value: string): string {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

function executionContracts(promptFiles: Record<string, string>) {
  return (["zh", "en"] as const).map((language) => ({
    execution_contract_id: `execution-contract:${language === "zh" ? "3" : "4"}${"0".repeat(63)}`,
    agent_id: "central_bank",
    language,
    immutable_contract_block_hash: immutablePromptContractHash(
      promptFiles[PROMPT_PATHS[language]] ?? "",
    ),
    execution_behavior_version: `execution-behavior:${language === "zh" ? "5" : "6"}${"0".repeat(63)}`,
    structured_output_schema_bindings: [],
    structured_output_schema_set_hash: HASH,
    structured_provider_contract_hash: HASH,
    runtime_tool_manifest_hash: HASH,
  }));
}

function candidate(input: {
  candidateId: string;
  parentId: string;
  parentPromptCommit: string;
  parentPromptFiles: Record<string, string>;
  promptFiles: Record<string, string>;
}): PromptCandidate {
  const promptHashes = {
    zh: sha256(input.promptFiles[PROMPT_PATHS.zh] ?? ""),
    en: sha256(input.promptFiles[PROMPT_PATHS.en] ?? ""),
  };
  const mutationCategories = ["EVIDENCE_PRIORITY"] as const;
  const withoutLineageHash: Omit<PromptCandidate, "privateLineageHash"> = {
    schemaVersion: "prompt_candidate_v1",
    candidateId: input.candidateId,
    parentId: input.parentId,
    parentPromptCommit: input.parentPromptCommit,
    parentPromptHashes: {
      zh: sha256(input.parentPromptFiles[PROMPT_PATHS.zh] ?? ""),
      en: sha256(input.parentPromptFiles[PROMPT_PATHS.en] ?? ""),
    },
    target: { agentId: "central_bank", stage: "agent_run", cohort: "cohort_default" },
    promptRefs: PROMPT_PATHS,
    promptHashes,
    trainingProjectionHash: HASH,
    excludedSampleIdsHash: HASH,
    mutatorConfigHash: HASH,
    mutatorCommit: input.parentPromptCommit,
    mutationCategories: [...mutationCategories],
    mutationSummary: promptMutationSummary(mutationCategories),
    hypothesis: promptMutationHypothesis(mutationCategories),
    behaviorContractHash: canonicalJsonHash(BEHAVIOR_TARGET_CONTRACT),
    privateStateArtifactHash: canonicalJsonHash(privateStateArtifact(input.candidateId)),
    createdAt: "2026-07-10T00:00:00.000Z",
  };
  return {
    ...withoutLineageHash,
    privateLineageHash: canonicalJsonHash(privateLineageBody(withoutLineageHash)),
  };
}

function candidateWithOverrides(
  value: PromptCandidate,
  overrides: Partial<PromptCandidate>,
): PromptCandidate {
  const { privateLineageHash: _privateLineageHash, ...withoutLineageHash } = {
    ...value,
    ...overrides,
  };
  return {
    ...withoutLineageHash,
    privateLineageHash: canonicalJsonHash(privateLineageBody(withoutLineageHash)),
  };
}

function stageFixture(
  options: {
    candidateOverrides?: Partial<PromptCandidate>;
    tamperLineage?: boolean;
    extraScopePath?: string;
    executionContractMismatch?: boolean;
  } = {},
) {
  const parentPromptFiles = {
    [PROMPT_PATHS.zh]: prompt("zh", "先核对时点与证据，再形成结论。"),
    [PROMPT_PATHS.en]: prompt("en", "Check timing and evidence before forming the conclusion."),
  };
  const privateRepo = initRepo({
    ...parentPromptFiles,
    "registry/knot/prompt_behavior_contract_v1.json": `${JSON.stringify(BEHAVIOR_CONTRACT_ARTIFACT, null, 2)}\n`,
  });
  const promptFiles = {
    [PROMPT_PATHS.zh]: prompt("zh", "先核对时点、证据和反例，再形成结论。"),
    [PROMPT_PATHS.en]: prompt(
      "en",
      "Check timing, evidence, and counter-cases before forming the conclusion.",
    ),
  };
  const baseCandidate = candidate({
    candidateId: "candidate-guard",
    parentId: "bootstrap-champion",
    parentPromptCommit: privateRepo.commit,
    parentPromptFiles,
    promptFiles,
  });
  const promptCandidate = candidateWithOverrides(baseCandidate, options.candidateOverrides ?? {});
  const lineage = privateLineageArtifact(promptCandidate);
  const tamperedLineage = options.tamperLineage
    ? { ...lineage, mutatorConfigHash: `sha256:${"9".repeat(64)}` }
    : lineage;
  const candidatePromptCommit = commitCandidate(privateRepo, promptCandidate, promptFiles, {
    privateLineage: tamperedLineage,
    ...(options.extraScopePath ? { extraFiles: { [options.extraScopePath]: "unexpected\n" } } : {}),
  });
  const closure = { catalog_hash: HASH, schema_hash: HASH, contract_hash: HASH };
  const codeRepo = initRepo({
    ...parentPromptFiles,
    "registry/prompt_checks/prompt_release_contract_ref_v2.json": `${JSON.stringify({ evaluation_contract: closure })}\n`,
  });
  const contracts = executionContracts(parentPromptFiles);
  if (options.executionContractMismatch && contracts[0]) {
    contracts[0].immutable_contract_block_hash = `sha256:${"8".repeat(64)}`;
  }
  const candidatePublication = buildPromptCandidatePublication({
    candidate: promptCandidate,
    promptSourceId: "private-prompts",
    candidatePromptCommit,
  });
  const registryRoot = mkdtempSync(join(tmpdir(), "mosaic-release-guard-"));
  roots.push(registryRoot);
  return {
    promptCandidate,
    candidatePromptCommit,
    candidatePublication,
    privateRepo,
    codeRepo,
    stageOptions: {
      registryRoot,
      releaseId: "release-guard",
      candidate: promptCandidate,
      candidatePublication,
      promotionDecision: promotionDecision(promptCandidate.candidateId),
      privatePromptRepo: privateRepo.root,
      privatePromptCommit: candidatePromptCommit,
      codeCommit: codeRepo.commit,
      codeRepo: codeRepo.root,
      cohort: "cohort_default",
      accountMode: "paper" as const,
      approvalPolicyId: "decision_release_manual_v1" as const,
      executionBehaviorReleaseRef: EXECUTION_RELEASE_REF,
    },
    deps: {
      specs: [SPEC],
      verifyPromotionDecision: async () => executionReleaseEnvironment(codeRepo.commit),
      loadExecutionBehaviorRelease: async () => ({
        execution_behavior_release_id: EXECUTION_RELEASE_ID,
        execution_behavior_release_hash: HASH,
        execution_contracts: contracts,
      }),
    },
  };
}

function promotionDecision(candidateId = "candidate-1"): PromptPromotionDecision {
  return {
    schemaVersion: "prompt_promotion_decision_v1",
    decisionId: "decision-1",
    experimentId: "experiment-1",
    familyId: "family-1",
    candidateId,
    policyVersion: "policy-v1",
    policyConfigHash: HASH,
    decision: "ELIGIBLE",
    reasons: ["all_promotion_gates_passed"],
    metricSummary: { holdout_paired_delta: 0.1 },
    evidenceHash: HASH,
    decidedAt: "2026-07-10T00:00:00.000Z",
  };
}

function canaryEvents(
  overrides: Omit<Partial<PromptReleaseCanaryEvent>, "schema_version"> = {},
  startIndex = 0,
  count = 20,
): PromptReleaseCanaryEvent[] {
  return Array.from({ length: count }, (_, offset) => {
    const index = startIndex + offset;
    return {
      schema_version: "prompt_release_canary_event_v2",
      event_id: `sha256:${createHash("sha256").update(`event-${index}`).digest("hex")}`,
      run_id: `run-${index}`,
      agent_invocation_id: `invocation-${index}`,
      release_id: "release-1",
      account_mode: "paper",
      traffic_percent: 10,
      agent: "central_bank",
      stage: "agent_run",
      stage_snapshot_hash: HASH,
      observed_at: "2026-07-10T01:30:00.000Z",
      prompt_source: "private",
      prompt_load_failed: false,
      schema_failed: false,
      fallback: false,
      source_failed: false,
      unsupported_influence_rejected: false,
      validator_rejected: false,
      latency_ms: 100,
      tokenizer_id: "cl100k_base",
      tokenizer_version: "1.0.21",
      context_window_tokens: 131_072,
      system_prompt_tokens: 1_000,
      system_prompt_cap_tokens: 32_768,
      token_budget_breached: false,
      validator_ids: ["macro.central_bank.output.v1"],
      duplicate_order_intent_count: 0,
      exposure_breach_count: 0,
      ...overrides,
    };
  });
}

function canaryRecords(
  overrides: Omit<Partial<PromptReleaseCanaryEvent>, "schema_version"> = {},
  startIndex = 0,
  count = 20,
) {
  return canaryEvents(overrides, startIndex, count).flatMap((event) => {
    const assignment = buildPromptReleaseCanaryAssignmentEvent({
      release: {
        release_id: event.release_id,
        account_mode: event.account_mode,
        traffic_percent: event.traffic_percent,
        stage_snapshot_hash: event.stage_snapshot_hash,
        lifecycle_state: "canary",
      },
      runId: event.run_id,
      agentInvocationId: event.agent_invocation_id,
      agent: event.agent,
      stage: event.stage,
      observedAt: "2026-07-10T01:29:00.000Z",
    });
    if (!assignment) throw new Error("canary assignment missing");
    return [assignment, event];
  });
}

function sloArtifact(overrides: Omit<Partial<PromptReleaseCanaryEvent>, "schema_version"> = {}) {
  const records = canaryRecords(overrides);
  const stageSnapshotHash = overrides.stage_snapshot_hash ?? HASH;
  const eventJournalPath = join(
    mkdtempSync(join(tmpdir(), "mosaic-canary-activation-")),
    "events.jsonl",
  );
  roots.push(dirname(eventJournalPath));
  writeFileSync(
    eventJournalPath,
    `${records.map((record) => JSON.stringify(record)).join("\n")}\n`,
  );
  return {
    eventJournalPath,
    artifact: buildPromptReleaseCanarySloArtifact({
      releaseId: "release-1",
      accountMode: "paper",
      trafficPercent: 10,
      canaryStartedAt: "2026-07-10T01:00:00.000Z",
      observationEndedAt: "2026-07-10T02:00:00.000Z",
      stageSnapshotHashes: { "central_bank:agent_run": stageSnapshotHash },
      records,
    }),
  };
}

describe("prompt release manager", () => {
  it.each([
    [
      "behavior contract",
      () => stageFixture({ candidateOverrides: { behaviorContractHash: HASH } }),
      "prompt_release_candidate_behavior_contract_mismatch",
    ],
    [
      "private lineage",
      () => stageFixture({ tamperLineage: true }),
      "prompt_release_private_candidate_lineage_mismatch",
    ],
    [
      "mutator parent",
      () => stageFixture({ candidateOverrides: { mutatorCommit: "0".repeat(40) } }),
      "prompt_release_candidate_mutator_parent_commit_mismatch",
    ],
    [
      "extra Candidate commit path",
      () => stageFixture({ extraScopePath: "unexpected.txt" }),
      "prompt_release_candidate_commit_scope_invalid",
    ],
    [
      "execution immutable contract",
      () => stageFixture({ executionContractMismatch: true }),
      "prompt_release_execution_contract_mismatch",
    ],
  ] as const)("rejects tampered %s evidence", async (_name, build, expectedError) => {
    const fixture = build();
    await expect(stagePromptRelease(fixture.stageOptions, fixture.deps)).rejects.toThrow(
      expectedError,
    );
  });

  it("rejects a Candidate publication rebound to a different commit", async () => {
    const fixture = stageFixture();
    const rebound = buildPromptCandidatePublication({
      candidate: fixture.promptCandidate,
      promptSourceId: fixture.candidatePublication.promptSourceId,
      candidatePromptCommit: fixture.promptCandidate.parentPromptCommit,
    });
    await expect(
      stagePromptRelease({ ...fixture.stageOptions, candidatePublication: rebound }, fixture.deps),
    ).rejects.toThrow("prompt_release_candidate_publication_commit_mismatch");
  });

  it("rejects a caller code commit that differs from the authorized experiment", async () => {
    const fixture = stageFixture();
    await expect(
      stagePromptRelease(fixture.stageOptions, {
        ...fixture.deps,
        verifyPromotionDecision: async () => executionReleaseEnvironment("0".repeat(40)),
      }),
    ).rejects.toThrow("prompt_release_authorized_code_commit_mismatch");
  });

  it("rejects an execution archive that differs from the authorized experiment", async () => {
    const fixture = stageFixture();
    const alternateReleaseId = `execution-behavior-release:${"3".repeat(64)}`;
    const alternateArchiveRef = `registry/prompt_checks/execution_behavior_releases/${"3".repeat(64)}--${"1".repeat(64)}.json`;
    await expect(
      stagePromptRelease(fixture.stageOptions, {
        ...fixture.deps,
        verifyPromotionDecision: async () => ({
          codeCommit: fixture.codeRepo.commit,
          executionBehaviorRelease: {
            release_id: alternateReleaseId,
            release_hash: HASH,
            archive_ref: alternateArchiveRef,
          },
        }),
      }),
    ).rejects.toThrow("prompt_release_authorized_execution_behavior_ref_mismatch");
  });

  it("rejects a merge commit as Candidate publication scope", async () => {
    const fixture = stageFixture();
    const currentBranch = execFileSync(
      "git",
      ["-C", fixture.privateRepo.root, "branch", "--show-current"],
      { encoding: "utf8" },
    ).trim();
    execFileSync("git", [
      "-C",
      fixture.privateRepo.root,
      "switch",
      "-q",
      "-c",
      "candidate-side-parent",
      fixture.promptCandidate.parentPromptCommit,
    ]);
    writeFileSync(join(fixture.privateRepo.root, "side.txt"), "side parent\n", "utf8");
    execFileSync("git", ["-C", fixture.privateRepo.root, "add", "side.txt"]);
    execFileSync("git", [
      "-C",
      fixture.privateRepo.root,
      "-c",
      "user.name=Codex Test",
      "-c",
      "user.email=codex@example.invalid",
      "commit",
      "-qm",
      "side parent",
    ]);
    execFileSync("git", ["-C", fixture.privateRepo.root, "switch", "-q", currentBranch]);
    execFileSync("git", [
      "-C",
      fixture.privateRepo.root,
      "-c",
      "user.name=Codex Test",
      "-c",
      "user.email=codex@example.invalid",
      "merge",
      "-q",
      "--no-ff",
      "candidate-side-parent",
      "-m",
      "merge candidate",
    ]);
    const mergeCommit = execFileSync("git", ["-C", fixture.privateRepo.root, "rev-parse", "HEAD"], {
      encoding: "utf8",
    }).trim();
    const publication = buildPromptCandidatePublication({
      candidate: fixture.promptCandidate,
      promptSourceId: fixture.candidatePublication.promptSourceId,
      candidatePromptCommit: mergeCommit,
    });
    await expect(
      stagePromptRelease(
        {
          ...fixture.stageOptions,
          candidatePublication: publication,
          privatePromptCommit: mergeCommit,
        },
        fixture.deps,
      ),
    ).rejects.toThrow("prompt_release_candidate_parent_commit_mismatch");
  });

  it("stages a hash-closed aggregate release and runs audited idempotent lifecycle steps", async () => {
    const parentPromptFiles = {
      [PROMPT_PATHS.zh]: prompt("zh", "先核对时点与证据，再形成结论。"),
      [PROMPT_PATHS.en]: prompt("en", "Check timing and evidence before forming the conclusion."),
    };
    const privateRepo = initRepo({
      ...parentPromptFiles,
      "registry/knot/prompt_behavior_contract_v1.json": `${JSON.stringify(BEHAVIOR_CONTRACT_ARTIFACT, null, 2)}\n`,
    });
    const baselinePromptFiles = {
      [PROMPT_PATHS.zh]: prompt("zh", "先核对时点、证据与反例，再形成结论。"),
      [PROMPT_PATHS.en]: prompt(
        "en",
        "Check timing, evidence, and counter-cases before forming the conclusion.",
      ),
    };
    const baselineCandidate = candidate({
      candidateId: "candidate-baseline",
      parentId: "bootstrap-champion",
      parentPromptCommit: privateRepo.commit,
      parentPromptFiles,
      promptFiles: baselinePromptFiles,
    });
    const baselinePromptCommit = commitCandidate(
      privateRepo,
      baselineCandidate,
      baselinePromptFiles,
    );
    const closure = {
      catalog_hash: HASH,
      schema_hash: HASH,
      contract_hash: HASH,
    };
    const codeRepo = initRepo({
      [PROMPT_PATHS.zh]: parentPromptFiles[PROMPT_PATHS.zh] ?? "",
      [PROMPT_PATHS.en]: parentPromptFiles[PROMPT_PATHS.en] ?? "",
      "registry/prompt_checks/prompt_release_contract_ref_v2.json": `${JSON.stringify({ evaluation_contract: closure })}\n`,
    });
    const registryRoot = mkdtempSync(join(tmpdir(), "mosaic-release-registry-"));
    roots.push(registryRoot);
    const baselineStageOptions = {
      registryRoot,
      releaseId: "baseline-1",
      candidate: baselineCandidate,
      candidatePublication: buildPromptCandidatePublication({
        candidate: baselineCandidate,
        promptSourceId: "private-prompts",
        candidatePromptCommit: baselinePromptCommit,
      }),
      promotionDecision: promotionDecision(baselineCandidate.candidateId),
      privatePromptRepo: privateRepo.root,
      privatePromptCommit: baselinePromptCommit,
      codeCommit: codeRepo.commit,
      codeRepo: codeRepo.root,
      cohort: "cohort_default",
      accountMode: "paper" as const,
      approvalPolicyId: "decision_release_manual_v1" as const,
      executionBehaviorReleaseRef: EXECUTION_RELEASE_REF,
    };
    const deps = {
      specs: [SPEC],
      now: () => "2026-07-10T00:00:00.000Z",
      verifyPromotionDecision: async () => executionReleaseEnvironment(codeRepo.commit),
      loadExecutionBehaviorRelease: async () => ({
        execution_behavior_release_id: EXECUTION_RELEASE_ID,
        execution_behavior_release_hash: HASH,
        execution_contracts: executionContracts(parentPromptFiles),
      }),
    };

    process.env.MOSAIC_PROMPT_RELEASE_AUTHORIZED_OPERATORS = "operator:test";
    const baselinePairWithoutHash = {
      agent: "central_bank",
      layer: "macro" as const,
      cohort: "cohort_default",
      stages: ["agent_run" as const],
      zh: { path: PROMPT_PATHS.zh, sha256: baselineCandidate.promptHashes.zh },
      en: { path: PROMPT_PATHS.en, sha256: baselineCandidate.promptHashes.en },
    };
    const baselinePairHash = releasePromptPairHash(baselinePairWithoutHash);
    const baselineDecision = promotionDecision(baselineCandidate.candidateId);
    const baseline = await buildPromptReleaseBaselineManifest(
      {
        releaseId: "baseline-1",
        privatePromptRepo: privateRepo.root,
        privatePromptCommit: baselinePromptCommit,
        codeCommit: codeRepo.commit,
        codeRepo: codeRepo.root,
        cohort: "cohort_default",
        accountMode: "paper",
        executionBehaviorReleaseRef: EXECUTION_RELEASE_REF,
        approvalRecord: {
          schema_version: "prompt_release_baseline_approval_record_v2",
          approval_policy_id: "decision_release_manual_v1",
          approved_by: "operator:test",
          release_evidence: {
            candidate_id: baselineCandidate.candidateId,
            candidate_hash: canonicalJsonHash(baselineCandidate),
            candidate_publication_hash: baselineStageOptions.candidatePublication.publicationHash,
            prompt_source_id: baselineStageOptions.candidatePublication.promptSourceId,
            promotion_decision_id: baselineDecision.decisionId,
            promotion_decision_hash: canonicalJsonHash(baselineDecision),
            experiment_id: baselineDecision.experimentId,
            mutated_agent: baselineCandidate.target.agentId,
            policy_version: baselineDecision.policyVersion,
            policy_config_hash: baselineDecision.policyConfigHash,
            candidate_prompt_hashes: baselineCandidate.promptHashes,
            private_state_artifact_hash: baselineCandidate.privateStateArtifactHash,
            behavior_contract_hash: baselineCandidate.behaviorContractHash,
            mutator_commit: baselineCandidate.mutatorCommit,
            mutator_config_hash: baselineCandidate.mutatorConfigHash,
          },
          canary_started_at: "2026-07-09T00:00:00.000Z",
          canary_ended_at: "2026-07-09T01:00:00.000Z",
          runtime_slo_summary: {
            passed: true,
            sample_count: 20,
            schema_failure_rate: 0,
            fallback_rate: 0,
            source_failure_rate: 0,
            unsupported_influence_rejection_rate: 0,
            validator_rejection_rate: 0,
            latency_p95_ms: 100,
            token_budget_breach_count: 0,
            duplicate_order_intent_count: 0,
            exposure_breach_count: 0,
          },
          runtime_slo_evidence: {
            schema_version: "prompt_release_canary_slo_evidence_v1",
            release_id: "baseline-1",
            account_mode: "paper",
            traffic_percent: 10,
            canary_started_at: "2026-07-09T00:00:00.000Z",
            observation_ended_at: "2026-07-09T01:00:00.000Z",
            eligible_event_count: 20,
            excluded_event_count: 0,
            excluded_count_by_reason: {},
            event_set_hash: HASH,
            stage_snapshot_hashes_hash: stageSnapshotHashesHash({
              "central_bank:agent_run": baselinePairHash,
            }),
            aggregator_id: "prompt_release_canary_slo",
            aggregator_version: "1",
            artifact_hash: HASH,
          },
          created_at: "2026-07-08T00:00:00.000Z",
          activated_at: "2026-07-09T01:00:00.000Z",
        },
      },
      deps,
    );
    expect(baseline.prompt_pairs).toHaveLength(1);
    expect(baseline.stage_snapshot_hashes).toEqual({
      "central_bank:agent_run": baselinePairHash,
    });
    await provisionPromptReleaseBaseline({
      registryRoot,
      manifest: baseline,
      privatePromptRepo: privateRepo.root,
      approvedBy: "operator:test",
      reason: "import previously approved deployment baseline",
      codeRepo: codeRepo.root,
      deps: {
        specs: [SPEC],
        loadExecutionBehaviorRelease: deps.loadExecutionBehaviorRelease,
      },
    });

    const promptFiles = {
      [PROMPT_PATHS.zh]: prompt("zh", "先核对时点、证据和最强反例，并明确传导路径后再形成结论。"),
      [PROMPT_PATHS.en]: prompt(
        "en",
        "Check timing, evidence, and the strongest counter-case, then state the transmission path before concluding.",
      ),
    };
    const promptCandidate = candidate({
      candidateId: "candidate-1",
      parentId: "baseline-1",
      parentPromptCommit: baselinePromptCommit,
      parentPromptFiles: baselinePromptFiles,
      promptFiles,
    });
    const candidatePromptCommit = commitCandidate(privateRepo, promptCandidate, promptFiles);
    expect(
      execFileSync(
        "git",
        [
          "-C",
          privateRepo.root,
          "diff-tree",
          "--no-commit-id",
          "--name-only",
          "-r",
          candidatePromptCommit,
        ],
        { encoding: "utf8" },
      )
        .trim()
        .split("\n")
        .sort(),
    ).toEqual(
      [
        PROMPT_PATHS.zh,
        PROMPT_PATHS.en,
        `registry/prompt_candidates_v2/${promptCandidate.candidateId}.json`,
        `registry/prompt_candidate_private_v1/${promptCandidate.candidateId}.json`,
        `registry/prompt_parameter_states_v1/${promptCandidate.target.cohort}/${promptCandidate.target.stage}/${promptCandidate.target.agentId}.json`,
        "registry/knot/prompt_parameter_bootstrap_release_v1.json",
      ].sort(),
    );
    const stageOptions = {
      ...baselineStageOptions,
      releaseId: "release-1",
      candidate: promptCandidate,
      candidatePublication: buildPromptCandidatePublication({
        candidate: promptCandidate,
        promptSourceId: "private-prompts",
        candidatePromptCommit,
      }),
      promotionDecision: promotionDecision(promptCandidate.candidateId),
      privatePromptCommit: candidatePromptCommit,
    };

    const staged = await stagePromptRelease(stageOptions, deps);
    await stagePromptRelease(stageOptions, deps);
    expect(staged.prompt_pairs).toHaveLength(1);
    expect(staged.bundled_fallback?.prompt_pairs).toHaveLength(1);
    expect(staged.release_evidence.candidate_id).toBe(promptCandidate.candidateId);
    expect(staged.release_evidence.promotion_decision_id).toBe("decision-1");
    expect(staged.release_evidence.private_state_artifact_hash).toBe(
      promptCandidate.privateStateArtifactHash,
    );

    delete process.env.MOSAIC_PROMPT_RELEASE_AUTHORIZED_OPERATORS;
    await expect(
      startPromptReleaseCanary({
        registryRoot,
        releaseId: "release-1",
        approvedBy: "operator:test",
        reason: "authorization is intentionally absent",
        trafficPercent: 10,
      }),
    ).rejects.toThrow("prompt_release_operator_not_authorized");
    const stagedRegistry = new ActivePromptReleaseRegistry(registryRoot);
    expect((await stagedRegistry.load("release-1"))?.lifecycle_state).toBe("staged");
    expect((await stagedRegistry.pointer()).current_release_id).toBe("baseline-1");
    process.env.MOSAIC_PROMPT_RELEASE_AUTHORIZED_OPERATORS = "operator:test";

    const canaryOptions = {
      registryRoot,
      releaseId: "release-1",
      approvedBy: "operator:test",
      reason: "candidate closure reviewed",
      trafficPercent: 10,
      deps: { now: () => "2026-07-10T01:00:00.000Z" },
    };
    await startPromptReleaseCanary(canaryOptions);
    await startPromptReleaseCanary(canaryOptions);
    const canaryRegistry = new ActivePromptReleaseRegistry(registryRoot);
    expect(await canaryRegistry.canaryPointer()).toMatchObject({
      current_release_id: "release-1",
      traffic_percent: 10,
    });
    const assignments = await Promise.all(
      Array.from({ length: 100 }, (_, index) =>
        canaryRegistry.resolveForRuntime(`assignment-${index}`),
      ),
    );
    expect(assignments.some((manifest) => manifest?.lifecycle_state === "canary")).toBe(true);
    expect(assignments.some((manifest) => manifest?.release_id === "baseline-1")).toBe(true);
    const stageSnapshotHash = staged.stage_snapshot_hashes["central_bank:agent_run"];
    if (!stageSnapshotHash) throw new Error("stage snapshot hash missing");
    const failingSlo = sloArtifact({ latency_ms: 120_001, stage_snapshot_hash: stageSnapshotHash });
    await expect(
      activatePromptRelease({
        registryRoot,
        releaseId: "release-1",
        approvedBy: "operator:test",
        reason: "asserted pass with excessive latency",
        sloArtifact: failingSlo.artifact,
        eventJournalPath: failingSlo.eventJournalPath,
        codeRepo: codeRepo.root,
        deps: {
          now: () => "2026-07-10T02:00:00.000Z",
          loadExecutionBehaviorRelease: deps.loadExecutionBehaviorRelease,
        },
      }),
    ).rejects.toThrow("prompt_release_runtime_slo_failed");
    const staleSlo = sloArtifact({ stage_snapshot_hash: stageSnapshotHash });
    await new PromptReleaseCanaryEventJournal(staleSlo.eventJournalPath).appendOnce(
      canaryRecords({ stage_snapshot_hash: stageSnapshotHash }, 100, 1),
    );
    await expect(
      activatePromptRelease({
        registryRoot,
        releaseId: "release-1",
        approvedBy: "operator:test",
        reason: "stale journal snapshot must not activate",
        sloArtifact: staleSlo.artifact,
        eventJournalPath: staleSlo.eventJournalPath,
        codeRepo: codeRepo.root,
        deps: {
          now: () => "2026-07-10T02:00:00.000Z",
          loadExecutionBehaviorRelease: deps.loadExecutionBehaviorRelease,
        },
      }),
    ).rejects.toThrow("prompt_release_canary_slo_journal_closure_mismatch");
    const passingSlo = sloArtifact({ stage_snapshot_hash: stageSnapshotHash });
    const activationOptions = {
      registryRoot,
      releaseId: "release-1",
      approvedBy: "operator:test",
      reason: "canary SLOs passed",
      sloArtifact: passingSlo.artifact,
      eventJournalPath: passingSlo.eventJournalPath,
      codeRepo: codeRepo.root,
      deps: {
        now: () => "2026-07-10T02:00:00.000Z",
        loadExecutionBehaviorRelease: deps.loadExecutionBehaviorRelease,
      },
    };
    await activatePromptRelease(activationOptions);
    await activatePromptRelease(activationOptions);
    const active = await new ActivePromptReleaseRegistry(registryRoot).resolveActive();
    expect(active?.release_id).toBe("release-1");
    expect(active?.prompt_commit).toBe(candidatePromptCommit);
    expect(
      privateStateAtCommit(privateRepo.root, active?.prompt_commit ?? "", promptCandidate),
    ).toEqual(privateStateArtifact(promptCandidate.candidateId));
    expect((await canaryRegistry.canaryPointer()).current_release_id).toBeNull();
    const rollbackOptions = {
      registryRoot,
      releaseId: "release-1",
      approvedBy: "operator:test",
      reason: "operational rollback drill",
      deps: { now: () => "2026-07-10T03:00:00.000Z" },
    };
    await rollbackPromptRelease(rollbackOptions);
    await rollbackPromptRelease(rollbackOptions);

    const registry = new ActivePromptReleaseRegistry(registryRoot);
    expect((await registry.pointer()).current_release_id).toBe("baseline-1");
    const restored = await registry.resolveActive();
    expect(restored?.prompt_commit).toBe(baselinePromptCommit);
    expect(
      privateStateAtCommit(privateRepo.root, restored?.prompt_commit ?? "", baselineCandidate),
    ).toEqual(privateStateArtifact(baselineCandidate.candidateId));
    const audit = readFileSync(join(registryRoot, "release-audit.jsonl"), "utf-8")
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line) as { event: string });
    expect(audit.map((row) => row.event)).toEqual([
      "baseline_provisioned",
      "staged",
      "canary",
      "active",
      "rolled_back",
    ]);
  });

  it("fails closed for unlisted operators", async () => {
    process.env.MOSAIC_PROMPT_RELEASE_AUTHORIZED_OPERATORS = "operator:allowed";
    await expect(
      startPromptReleaseCanary({
        registryRoot: "/unused",
        releaseId: "release-1",
        approvedBy: "operator:unlisted",
        reason: "not authorized",
        trafficPercent: 10,
      }),
    ).rejects.toThrow("prompt_release_operator_not_authorized");
  });

  it("rejects duplicate records and incomplete canary invocations", () => {
    const duplicate = canaryRecords();
    const first = duplicate[0];
    const third = duplicate[2];
    if (!first || !third) throw new Error("canary record fixture incomplete");
    duplicate[2] = { ...third, event_id: first.event_id };
    expect(() =>
      buildPromptReleaseCanarySloArtifact({
        releaseId: "release-1",
        accountMode: "paper",
        trafficPercent: 10,
        canaryStartedAt: "2026-07-10T01:00:00.000Z",
        observationEndedAt: "2026-07-10T02:00:00.000Z",
        stageSnapshotHashes: { "central_bank:agent_run": HASH },
        records: duplicate,
      }),
    ).toThrow("prompt_release_canary_slo_duplicate_event");
    expect(() =>
      buildPromptReleaseCanarySloArtifact({
        releaseId: "release-1",
        accountMode: "paper",
        trafficPercent: 10,
        canaryStartedAt: "2026-07-10T01:00:00.000Z",
        observationEndedAt: "2026-07-10T02:00:00.000Z",
        stageSnapshotHashes: { "central_bank:agent_run": HASH },
        records: canaryRecords().slice(1),
      }),
    ).toThrow("prompt_release_canary_slo_incomplete_invocations");
  });
});
