import { execFile } from "node:child_process";
import { z } from "zod";
import { canonicalJsonHash, compareCanonicalStrings } from "../agents/helpers/canonical_json.js";
import {
  extractCohortBehavior,
  immutablePromptContractText,
  validateCohortBehaviorLanguage,
} from "../agents/prompts/cohort_behavior.js";
import { containsPrivateKnotPromptContent } from "../agents/prompts/private_knot_prompt_markers.js";
import {
  type ActivePromptReleaseManifest,
  ActivePromptReleaseManifestSchema,
  assertReleasePromptStageClosure,
  PromptReleaseEvidenceSchema,
  type PromptReleaseExecutionBehaviorBinding,
  PromptReleaseExecutionBehaviorBindingSchema,
  PromptReleaseRuntimeSloEvidenceSchema,
  PromptReleaseRuntimeSloSummarySchema,
  promptReleaseRuntimeSloPasses,
  releasePromptSetHash,
} from "../agents/prompts/prompt_release_contract.js";
import {
  buildReleasePromptPairsAtCommit,
  loadPromptReleaseClosureAtCommit,
} from "../agents/prompts/release_prompt_loader.js";
import type { RuntimeAgentSpec } from "../agents/prompts/runtime_agent_spec.js";
import { RUNTIME_AGENT_SPECS } from "../agents/prompts/runtime_agent_spec.js";
import { findRepoRoot } from "../bridge/python.js";
import {
  type ExecutionBehaviorReleaseManifest,
  loadExecutionBehaviorReleaseArchiveAtCommit,
} from "./execution_behavior_release.js";
import {
  type PromptCandidate,
  PromptCandidateSchema,
  type PromptPromotionDecision,
  PromptPromotionDecisionSchema,
} from "./prompt_optimizer_contract.js";
import {
  buildPromptReleaseCanarySloArtifact,
  PromptReleaseCanaryEventJournal,
  type PromptReleaseCanarySloArtifact,
  PromptReleaseCanarySloArtifactSchema,
  stageSnapshotHashesHash,
} from "./prompt_release_canary_slo.js";
import { ActivePromptReleaseRegistry } from "./release_registry.js";

export const DEFAULT_PROMPT_RELEASE_ROLLBACK_TRIGGERS = [
  "schema_failure_rate_gt_0",
  "fallback_rate_gt_0.10",
  "source_failure_rate_gt_0.05",
  "unsupported_influence_rejection_rate_gt_0.05",
  "validator_rejection_rate_gt_0.05",
  "latency_p95_ms_gt_120000",
  "token_budget_breach_count_gt_0",
  "duplicate_order_intent_count_gt_0",
  "exposure_breach_count_gt_0",
] as const;

const PRIVATE_PROMPT_BOOTSTRAP_RELEASE_REF =
  "registry/knot/prompt_parameter_bootstrap_release_v1.json";

type RuntimeSloSummary = NonNullable<ActivePromptReleaseManifest["runtime_slo_summary"]>;

export interface PromptReleaseManagerDependencies {
  specs?: ReadonlyArray<RuntimeAgentSpec>;
  now?: () => string;
  verifyPromotionDecision?: (
    candidate: PromptCandidate,
    decision: PromptPromotionDecision,
  ) => Promise<void>;
  loadExecutionBehaviorRelease?: (opts: {
    repo: string;
    commit: string;
    archiveRef: string;
  }) => Promise<
    Pick<
      ExecutionBehaviorReleaseManifest,
      "execution_behavior_release_id" | "execution_behavior_release_hash" | "private_prompt_commit"
    >
  >;
}

export interface StagePromptReleaseOptions {
  registryRoot: string;
  releaseId: string;
  candidate: PromptCandidate;
  promotionDecision: PromptPromotionDecision;
  privatePromptRepo: string;
  privatePromptCommit: string;
  codeCommit: string;
  codeRepo?: string;
  cohort: string;
  accountMode: "paper" | "backtest" | "live";
  approvalPolicyId: "domain_release_manual_v1" | "decision_release_manual_v1";
  executionBehaviorReleaseRef: string;
}

export const PromptReleaseBaselineApprovalRecordSchema = z
  .object({
    schema_version: z.literal("prompt_release_baseline_approval_record_v1"),
    approval_policy_id: z.enum(["domain_release_manual_v1", "decision_release_manual_v1"]),
    approved_by: z.string().trim().min(1),
    release_evidence: PromptReleaseEvidenceSchema,
    canary_started_at: z.string().trim().min(1),
    canary_ended_at: z.string().trim().min(1),
    runtime_slo_summary: PromptReleaseRuntimeSloSummarySchema,
    runtime_slo_evidence: PromptReleaseRuntimeSloEvidenceSchema,
    created_at: z.string().trim().min(1),
    activated_at: z.string().trim().min(1),
  })
  .strict();

export type PromptReleaseBaselineApprovalRecord = z.infer<
  typeof PromptReleaseBaselineApprovalRecordSchema
>;

export interface BuildPromptReleaseBaselineOptions {
  releaseId: string;
  privatePromptRepo: string;
  privatePromptCommit: string;
  codeCommit: string;
  codeRepo?: string;
  cohort: string;
  accountMode: "paper" | "backtest" | "live";
  executionBehaviorReleaseRef: string;
  approvalRecord: PromptReleaseBaselineApprovalRecord;
}

async function executionBehaviorBindingAtCommit(opts: {
  repo: string;
  commit: string;
  promptCommit: string;
  archiveRef: string;
  deps: PromptReleaseManagerDependencies;
}): Promise<PromptReleaseExecutionBehaviorBinding> {
  const archiveRef = opts.archiveRef.trim();
  if (!archiveRef) throw new Error("prompt_release_execution_behavior_ref_required");
  const release = await (
    opts.deps.loadExecutionBehaviorRelease ?? loadExecutionBehaviorReleaseArchiveAtCommit
  )({ repo: opts.repo, commit: opts.commit, archiveRef });
  if (release.private_prompt_commit !== opts.promptCommit) {
    throw new Error("prompt_release_execution_behavior_prompt_commit_mismatch");
  }
  return PromptReleaseExecutionBehaviorBindingSchema.parse({
    release_id: release.execution_behavior_release_id,
    release_hash: release.execution_behavior_release_hash,
    archive_ref: archiveRef,
  });
}

async function assertExecutionBehaviorBindingAtCommit(opts: {
  repo: string;
  commit: string;
  promptCommit: string;
  binding: PromptReleaseExecutionBehaviorBinding;
  deps: PromptReleaseManagerDependencies;
}): Promise<void> {
  const resolved = await executionBehaviorBindingAtCommit({
    repo: opts.repo,
    commit: opts.commit,
    promptCommit: opts.promptCommit,
    archiveRef: opts.binding.archive_ref,
    deps: opts.deps,
  });
  if (canonicalJsonHash(resolved) !== canonicalJsonHash(opts.binding)) {
    throw new Error("prompt_release_execution_behavior_binding_mismatch");
  }
}

function runGit(repo: string, args: ReadonlyArray<string>): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    execFile(
      "git",
      ["-C", repo, ...args],
      { encoding: "buffer", maxBuffer: 8 * 1024 * 1024 },
      (error, stdout, stderr) => {
        if (error) {
          reject(
            new Error(`prompt_release_git_failed:${args[0]}:${stderr.toString("utf-8").trim()}`),
          );
        } else {
          resolve(stdout);
        }
      },
    );
  });
}

async function fullCommit(repo: string, commit: string): Promise<string> {
  return (await runGit(repo, ["rev-parse", "--verify", `${commit}^{commit}`]))
    .toString("utf-8")
    .trim();
}

async function assertCleanCodeCheckout(repo: string, expectedCommit: string): Promise<void> {
  const head = await fullCommit(repo, "HEAD");
  if (head !== expectedCommit) throw new Error("prompt_release_code_checkout_mismatch");
  if ((await runGit(repo, ["status", "--porcelain"])).toString("utf-8").trim()) {
    throw new Error("prompt_release_code_checkout_dirty");
  }
}

function requireEligibleCandidate(
  rawCandidate: PromptCandidate,
  rawDecision: PromptPromotionDecision,
  cohort: string,
): { candidate: PromptCandidate; decision: PromptPromotionDecision } {
  const candidate = PromptCandidateSchema.parse(rawCandidate);
  const decision = PromptPromotionDecisionSchema.parse(rawDecision);
  if (candidate.target.cohort !== cohort)
    throw new Error("prompt_release_candidate_cohort_mismatch");
  if (
    decision.decision !== "ELIGIBLE" ||
    decision.candidateId !== candidate.candidateId ||
    decision.experimentId.trim().length === 0
  ) {
    throw new Error("prompt_release_candidate_not_eligible");
  }
  return { candidate, decision };
}

async function assertCandidateRecordAtCommit(input: {
  repo: string;
  commit: string;
  candidate: PromptCandidate;
}): Promise<void> {
  const ref = `registry/prompt_candidates_v2/${input.candidate.candidateId}.json`;
  let value: PromptCandidate;
  try {
    value = PromptCandidateSchema.parse(
      JSON.parse((await runGit(input.repo, ["show", `${input.commit}:${ref}`])).toString("utf-8")),
    );
  } catch {
    throw new Error("prompt_release_private_candidate_record_missing");
  }
  if (canonicalJsonHash(value) !== canonicalJsonHash(input.candidate)) {
    throw new Error("prompt_release_private_candidate_record_mismatch");
  }
}

async function promptTextAtCommit(repo: string, commit: string, path: string): Promise<string> {
  return (await runGit(repo, ["show", `${commit}:${path}`])).toString("utf-8");
}

function privateCandidateStateRef(candidate: PromptCandidate): string {
  return (
    `registry/prompt_parameter_states_v1/${candidate.target.cohort}/` +
    `${candidate.target.stage}/${candidate.target.agentId}.json`
  );
}

async function assertPrivateCandidateStateArtifact(input: {
  repo: string;
  commit: string;
  candidate: PromptCandidate;
}): Promise<void> {
  const ref = privateCandidateStateRef(input.candidate);
  let artifact: unknown;
  try {
    artifact = JSON.parse(
      (await runGit(input.repo, ["show", `${input.commit}:${ref}`])).toString("utf-8"),
    );
  } catch {
    throw new Error("prompt_release_private_state_artifact_missing");
  }
  if (canonicalJsonHash(artifact) !== input.candidate.privateStateArtifactHash) {
    throw new Error("prompt_release_private_state_artifact_mismatch");
  }
}

async function assertCandidateCommitScope(input: {
  repo: string;
  commit: string;
  candidate: PromptCandidate;
}): Promise<void> {
  const parents = (await runGit(input.repo, ["show", "-s", "--format=%P", input.commit]))
    .toString("utf-8")
    .trim()
    .split(/\s+/u)
    .filter(Boolean);
  if (parents.length !== 1 || parents[0] !== input.candidate.parentPromptCommit) {
    throw new Error("prompt_release_candidate_parent_commit_mismatch");
  }
  const recordRef = `registry/prompt_candidates_v2/${input.candidate.candidateId}.json`;
  const privateLineageRef = `registry/prompt_candidate_private_v1/${input.candidate.candidateId}.json`;
  const privateStateRef = privateCandidateStateRef(input.candidate);
  const changed = (
    await runGit(input.repo, ["diff-tree", "--no-commit-id", "--name-only", "-r", input.commit])
  )
    .toString("utf-8")
    .trim()
    .split("\n")
    .filter(Boolean)
    .sort();
  const expected = [
    input.candidate.promptRefs.zh,
    input.candidate.promptRefs.en,
    recordRef,
    privateLineageRef,
    privateStateRef,
    PRIVATE_PROMPT_BOOTSTRAP_RELEASE_REF,
  ].sort();
  if (JSON.stringify(changed) !== JSON.stringify(expected)) {
    throw new Error("prompt_release_candidate_commit_scope_invalid");
  }
}

function promptToolNames(text: string): string[] {
  return [...new Set(text.match(/\bget_[a-z0-9_]+\b/gu) ?? [])].sort();
}

async function assertPinnedPromptTree(input: {
  repo: string;
  commit: string;
  candidate: PromptCandidate;
  promptPairs: ActivePromptReleaseManifest["prompt_pairs"];
  specs: ReadonlyArray<RuntimeAgentSpec>;
  base: ActivePromptReleaseManifest | null;
}): Promise<void> {
  await assertPromptTreeContractsAtCommit(input);
  const baseByAgent = new Map(input.base?.prompt_pairs.map((pair) => [pair.agent, pair]) ?? []);
  for (const spec of input.specs) {
    const pair = input.promptPairs.find((value) => value.agent === spec.agent);
    if (!pair) throw new Error(`prompt_release_prompt_pair_missing:${spec.agent}`);
    const basePair = baseByAgent.get(spec.agent);
    if (input.base && !basePair) throw new Error(`prompt_release_base_pair_missing:${spec.agent}`);
    if (basePair && spec.agent !== input.candidate.target.agentId) {
      if (canonicalJsonHash(pair) !== canonicalJsonHash(basePair)) {
        throw new Error(`prompt_release_non_target_pair_changed:${spec.agent}`);
      }
    }
  }
  const targetPair = input.promptPairs.find(
    (pair) => pair.agent === input.candidate.target.agentId,
  );
  if (!targetPair) throw new Error("prompt_release_mutated_agent_pair_missing");
  const parentPair = (
    await buildReleasePromptPairsAtCommit({
      repo: input.repo,
      commit: input.candidate.parentPromptCommit,
      cohort: input.candidate.target.cohort,
      specs: input.specs,
    })
  ).find((pair) => pair.agent === input.candidate.target.agentId);
  if (
    !parentPair ||
    parentPair.zh.sha256 !== input.candidate.parentPromptHashes.zh ||
    parentPair.en.sha256 !== input.candidate.parentPromptHashes.en
  ) {
    throw new Error("prompt_release_candidate_parent_pair_mismatch");
  }
  const [parentZh, parentEn, candidateZh, candidateEn] = await Promise.all([
    promptTextAtCommit(input.repo, input.candidate.parentPromptCommit, parentPair.zh.path),
    promptTextAtCommit(input.repo, input.candidate.parentPromptCommit, parentPair.en.path),
    promptTextAtCommit(input.repo, input.commit, targetPair.zh.path),
    promptTextAtCommit(input.repo, input.commit, targetPair.en.path),
  ]);
  if (
    immutablePromptContractText(parentZh) !== immutablePromptContractText(candidateZh) ||
    immutablePromptContractText(parentEn) !== immutablePromptContractText(candidateEn)
  ) {
    throw new Error("prompt_release_candidate_immutable_contract_changed");
  }
}

async function assertPromptTreeContractsAtCommit(input: {
  repo: string;
  commit: string;
  promptPairs: ActivePromptReleaseManifest["prompt_pairs"];
  specs: ReadonlyArray<RuntimeAgentSpec>;
}): Promise<void> {
  for (const spec of input.specs) {
    const pair = input.promptPairs.find((value) => value.agent === spec.agent);
    if (!pair) throw new Error(`prompt_release_prompt_pair_missing:${spec.agent}`);
    const [zh, en] = await Promise.all([
      promptTextAtCommit(input.repo, input.commit, pair.zh.path),
      promptTextAtCommit(input.repo, input.commit, pair.en.path),
    ]);
    validateCohortBehaviorLanguage(extractCohortBehavior(zh), "zh");
    validateCohortBehaviorLanguage(extractCohortBehavior(en), "en");
    if (containsPrivateKnotPromptContent(`${zh}\n${en}`)) {
      throw new Error(`prompt_release_private_knot_content:${spec.agent}`);
    }
    const expectedTools = [...spec.requiredTools].sort();
    if (
      JSON.stringify(promptToolNames(zh)) !== JSON.stringify(expectedTools) ||
      JSON.stringify(promptToolNames(en)) !== JSON.stringify(expectedTools)
    ) {
      throw new Error(`prompt_release_tool_contract_mismatch:${spec.agent}`);
    }
  }
}

function now(deps: PromptReleaseManagerDependencies): string {
  return deps.now?.() ?? new Date().toISOString();
}

function sortedObjectJson(value: object | null): string {
  if (!value) return "null";
  return JSON.stringify(
    Object.fromEntries(
      Object.entries(value).sort(([left], [right]) => compareCanonicalStrings(left, right)),
    ),
  );
}

function assertAuthorizedOperator(operator: string): void {
  const configured = new Set(
    (process.env.MOSAIC_PROMPT_RELEASE_AUTHORIZED_OPERATORS ?? "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
  );
  if (!configured.has(operator)) throw new Error("prompt_release_operator_not_authorized");
}

export async function stagePromptRelease(
  opts: StagePromptReleaseOptions,
  deps: PromptReleaseManagerDependencies = {},
): Promise<ActivePromptReleaseManifest> {
  const codeRepo = opts.codeRepo ?? findRepoRoot();
  const specs = deps.specs ?? RUNTIME_AGENT_SPECS;
  const { candidate, decision } = requireEligibleCandidate(
    opts.candidate,
    opts.promotionDecision,
    opts.cohort,
  );
  if (!deps.verifyPromotionDecision) {
    throw new Error("prompt_release_promotion_authority_required");
  }
  await deps.verifyPromotionDecision(candidate, decision);
  if (
    ["cro", "alpha_discovery", "autonomous_execution", "cio"].includes(candidate.target.agentId) &&
    opts.approvalPolicyId !== "decision_release_manual_v1"
  ) {
    throw new Error("prompt_release_decision_policy_required");
  }
  const [promptCommit, codeCommit] = await Promise.all([
    fullCommit(opts.privatePromptRepo, opts.privatePromptCommit),
    fullCommit(codeRepo, opts.codeCommit),
  ]);
  if (promptCommit !== opts.privatePromptCommit || codeCommit !== opts.codeCommit) {
    throw new Error("prompt_release_requires_full_commit_ids");
  }
  await assertCleanCodeCheckout(codeRepo, codeCommit);
  const executionBehaviorRelease = await executionBehaviorBindingAtCommit({
    repo: codeRepo,
    commit: codeCommit,
    promptCommit,
    archiveRef: opts.executionBehaviorReleaseRef,
    deps,
  });
  await assertCandidateRecordAtCommit({
    repo: opts.privatePromptRepo,
    commit: promptCommit,
    candidate,
  });
  await assertCandidateCommitScope({
    repo: opts.privatePromptRepo,
    commit: promptCommit,
    candidate,
  });
  await assertPrivateCandidateStateArtifact({
    repo: opts.privatePromptRepo,
    commit: promptCommit,
    candidate,
  });
  const registry = new ActivePromptReleaseRegistry(opts.registryRoot);
  const pointer = await registry.pointer();
  const base = pointer.current_release_id ? await registry.load(pointer.current_release_id) : null;
  if (pointer.current_release_id && !base) throw new Error("prompt_release_base_manifest_missing");
  if (
    base &&
    (candidate.parentId !== base.release_id ||
      candidate.parentPromptCommit !== base.prompt_commit ||
      base.activation_scope.cohort !== candidate.target.cohort)
  ) {
    throw new Error("prompt_release_candidate_active_champion_mismatch");
  }
  const promptPairs = await buildReleasePromptPairsAtCommit({
    repo: opts.privatePromptRepo,
    commit: promptCommit,
    cohort: opts.cohort,
    specs,
  });
  await assertPinnedPromptTree({
    repo: opts.privatePromptRepo,
    commit: promptCommit,
    candidate,
    promptPairs,
    specs,
    base,
  });
  const stageSnapshotHashes = Object.fromEntries(
    promptPairs.flatMap((pair) =>
      pair.stages.map((stage) => [`${pair.agent}:${stage}`, pair.pair_hash] as const),
    ),
  );
  const mutatedPair = promptPairs.find((pair) => pair.agent === candidate.target.agentId);
  if (!mutatedPair) throw new Error("prompt_release_mutated_agent_pair_missing");
  if (
    !mutatedPair.stages.includes(candidate.target.stage) ||
    mutatedPair.cohort !== candidate.target.cohort ||
    mutatedPair.zh.path !== candidate.promptRefs.zh ||
    mutatedPair.en.path !== candidate.promptRefs.en ||
    mutatedPair.zh.sha256 !== candidate.promptHashes.zh ||
    mutatedPair.en.sha256 !== candidate.promptHashes.en
  ) {
    throw new Error("prompt_release_candidate_prompt_pair_mismatch");
  }

  const closure = await loadPromptReleaseClosureAtCommit({ repo: codeRepo, commit: codeCommit });
  const fallbackPairs = await buildReleasePromptPairsAtCommit({
    repo: codeRepo,
    commit: codeCommit,
    cohort: opts.cohort,
    specs,
  });
  const bundledFallback: ActivePromptReleaseManifest["bundled_fallback"] = {
    prompt_commit: codeCommit,
    prompt_hash: releasePromptSetHash(fallbackPairs),
    prompt_pairs: fallbackPairs,
    schema_hash: closure.schema_hash,
    catalog_hash: closure.catalog_hash,
  };

  const createdAt = now(deps);
  const releaseEvidence = {
    candidate_id: candidate.candidateId,
    candidate_hash: canonicalJsonHash(candidate),
    promotion_decision_id: decision.decisionId,
    promotion_decision_hash: canonicalJsonHash(decision),
    experiment_id: decision.experimentId,
    mutated_agent: candidate.target.agentId,
    policy_version: decision.policyVersion,
    policy_config_hash: decision.policyConfigHash,
    candidate_prompt_hashes: candidate.promptHashes,
    private_state_artifact_hash: candidate.privateStateArtifactHash,
  };
  const manifest: ActivePromptReleaseManifest = {
    schema_version: "active_prompt_release_manifest_v2",
    release_id: opts.releaseId,
    base_release_id: pointer.current_release_id,
    lifecycle_state: "staged",
    prompt_commit: promptCommit,
    code_commit: codeCommit,
    execution_behavior_release: executionBehaviorRelease,
    prompt_hash: releasePromptSetHash(promptPairs),
    prompt_pairs: promptPairs,
    stage_snapshot_hashes: stageSnapshotHashes,
    catalog_hash: closure.catalog_hash,
    schema_hash: closure.schema_hash,
    evaluation_contract_hash: closure.contract_hash,
    release_evidence: releaseEvidence,
    activation_scope: {
      cohort: opts.cohort,
      account_mode: opts.accountMode,
      traffic_percent: 0,
    },
    approval_policy_id: opts.approvalPolicyId,
    approved_by: null,
    canary_started_at: null,
    canary_ended_at: null,
    runtime_slo_summary: null,
    runtime_slo_evidence: null,
    rollback_triggers: [...DEFAULT_PROMPT_RELEASE_ROLLBACK_TRIGGERS],
    previous_approved_release_id: pointer.current_release_id,
    bundled_fallback: bundledFallback,
    created_at: createdAt,
    activated_at: null,
    rolled_back_at: null,
  };
  assertReleasePromptStageClosure(
    manifest,
    specs.flatMap((spec) =>
      spec.stages.map((stage) => ({ agent: spec.agent, layer: spec.layer, stage: stage.stage })),
    ),
  );
  await registry.stage(manifest);
  return manifest;
}

export async function buildPromptReleaseBaselineManifest(
  opts: BuildPromptReleaseBaselineOptions,
  deps: PromptReleaseManagerDependencies = {},
): Promise<ActivePromptReleaseManifest> {
  const approval = PromptReleaseBaselineApprovalRecordSchema.parse(opts.approvalRecord);
  const codeRepo = opts.codeRepo ?? findRepoRoot();
  const specs = deps.specs ?? RUNTIME_AGENT_SPECS;
  const [promptCommit, codeCommit] = await Promise.all([
    fullCommit(opts.privatePromptRepo, opts.privatePromptCommit),
    fullCommit(codeRepo, opts.codeCommit),
  ]);
  if (promptCommit !== opts.privatePromptCommit || codeCommit !== opts.codeCommit) {
    throw new Error("prompt_release_requires_full_commit_ids");
  }
  await assertCleanCodeCheckout(codeRepo, codeCommit);
  const executionBehaviorRelease = await executionBehaviorBindingAtCommit({
    repo: codeRepo,
    commit: codeCommit,
    promptCommit,
    archiveRef: opts.executionBehaviorReleaseRef,
    deps,
  });
  const promptPairs = await buildReleasePromptPairsAtCommit({
    repo: opts.privatePromptRepo,
    commit: promptCommit,
    cohort: opts.cohort,
    specs,
  });
  await assertPromptTreeContractsAtCommit({
    repo: opts.privatePromptRepo,
    commit: promptCommit,
    promptPairs,
    specs,
  });
  const stageSnapshotHashes = Object.fromEntries(
    promptPairs.flatMap((pair) =>
      pair.stages.map((stage) => [`${pair.agent}:${stage}`, pair.pair_hash] as const),
    ),
  );
  const approvedPair = promptPairs.find(
    (pair) => pair.agent === approval.release_evidence.mutated_agent,
  );
  if (
    !approvedPair ||
    approvedPair.zh.sha256 !== approval.release_evidence.candidate_prompt_hashes.zh ||
    approvedPair.en.sha256 !== approval.release_evidence.candidate_prompt_hashes.en
  ) {
    throw new Error("prompt_release_baseline_approved_prompt_mismatch");
  }
  const evidence = approval.runtime_slo_evidence;
  if (
    evidence.release_id !== opts.releaseId ||
    evidence.account_mode !== opts.accountMode ||
    evidence.canary_started_at !== approval.canary_started_at ||
    evidence.eligible_event_count !== approval.runtime_slo_summary.sample_count ||
    evidence.stage_snapshot_hashes_hash !== stageSnapshotHashesHash(stageSnapshotHashes)
  ) {
    throw new Error("prompt_release_baseline_approval_evidence_mismatch");
  }
  const closure = await loadPromptReleaseClosureAtCommit({ repo: codeRepo, commit: codeCommit });
  const fallbackPairs = await buildReleasePromptPairsAtCommit({
    repo: codeRepo,
    commit: codeCommit,
    cohort: opts.cohort,
    specs,
  });
  const manifest = ActivePromptReleaseManifestSchema.parse({
    schema_version: "active_prompt_release_manifest_v2",
    release_id: opts.releaseId,
    base_release_id: null,
    lifecycle_state: "active",
    prompt_commit: promptCommit,
    code_commit: codeCommit,
    execution_behavior_release: executionBehaviorRelease,
    prompt_hash: releasePromptSetHash(promptPairs),
    prompt_pairs: promptPairs,
    stage_snapshot_hashes: stageSnapshotHashes,
    catalog_hash: closure.catalog_hash,
    schema_hash: closure.schema_hash,
    evaluation_contract_hash: closure.contract_hash,
    release_evidence: approval.release_evidence,
    activation_scope: {
      cohort: opts.cohort,
      account_mode: opts.accountMode,
      traffic_percent: 100,
    },
    approval_policy_id: approval.approval_policy_id,
    approved_by: approval.approved_by,
    canary_started_at: approval.canary_started_at,
    canary_ended_at: approval.canary_ended_at,
    runtime_slo_summary: approval.runtime_slo_summary,
    runtime_slo_evidence: approval.runtime_slo_evidence,
    rollback_triggers: [...DEFAULT_PROMPT_RELEASE_ROLLBACK_TRIGGERS],
    previous_approved_release_id: null,
    bundled_fallback: {
      prompt_commit: codeCommit,
      prompt_hash: releasePromptSetHash(fallbackPairs),
      prompt_pairs: fallbackPairs,
      schema_hash: closure.schema_hash,
      catalog_hash: closure.catalog_hash,
    },
    created_at: approval.created_at,
    activated_at: approval.activated_at,
    rolled_back_at: null,
  });
  assertReleasePromptStageClosure(
    manifest,
    specs.flatMap((spec) =>
      spec.stages.map((stage) => ({ agent: spec.agent, layer: spec.layer, stage: stage.stage })),
    ),
  );
  return manifest;
}

export async function provisionPromptReleaseBaseline(opts: {
  registryRoot: string;
  manifest: ActivePromptReleaseManifest;
  privatePromptRepo: string;
  approvedBy: string;
  reason: string;
  codeRepo?: string;
  deps?: PromptReleaseManagerDependencies;
}): Promise<ActivePromptReleaseManifest> {
  assertAuthorizedOperator(opts.approvedBy);
  if (!opts.reason.trim()) throw new Error("prompt_release_baseline_reason_required");
  const manifest = ActivePromptReleaseManifestSchema.parse(opts.manifest);
  if (manifest.lifecycle_state !== "active") {
    throw new Error("prompt_release_baseline_must_be_active");
  }
  if (manifest.approved_by !== opts.approvedBy) {
    throw new Error("prompt_release_baseline_operator_mismatch");
  }
  const codeRepo = opts.codeRepo ?? findRepoRoot();
  const [promptCommit, codeCommit] = await Promise.all([
    fullCommit(opts.privatePromptRepo, manifest.prompt_commit),
    fullCommit(codeRepo, manifest.code_commit),
  ]);
  if (promptCommit !== manifest.prompt_commit || codeCommit !== manifest.code_commit) {
    throw new Error("prompt_release_requires_full_commit_ids");
  }
  await assertCleanCodeCheckout(codeRepo, codeCommit);
  await assertExecutionBehaviorBindingAtCommit({
    repo: codeRepo,
    commit: codeCommit,
    promptCommit,
    binding: manifest.execution_behavior_release,
    deps: opts.deps ?? {},
  });
  const closure = await loadPromptReleaseClosureAtCommit({ repo: codeRepo, commit: codeCommit });
  if (
    closure.catalog_hash !== manifest.catalog_hash ||
    closure.schema_hash !== manifest.schema_hash ||
    closure.contract_hash !== manifest.evaluation_contract_hash
  ) {
    throw new Error("prompt_release_local_contract_closure_drift");
  }
  const fallback = manifest.bundled_fallback;
  if (!fallback) throw new Error("prompt_release_baseline_bundled_fallback_required");
  if (
    fallback.prompt_commit !== codeCommit ||
    fallback.catalog_hash !== closure.catalog_hash ||
    fallback.schema_hash !== closure.schema_hash
  ) {
    throw new Error("prompt_release_baseline_bundled_fallback_closure_mismatch");
  }
  const specs = opts.deps?.specs ?? RUNTIME_AGENT_SPECS;
  const [privatePairs, fallbackPairs] = await Promise.all([
    buildReleasePromptPairsAtCommit({
      repo: opts.privatePromptRepo,
      commit: promptCommit,
      cohort: manifest.activation_scope.cohort,
      specs,
    }),
    buildReleasePromptPairsAtCommit({
      repo: codeRepo,
      commit: fallback.prompt_commit,
      cohort: manifest.activation_scope.cohort,
      specs,
    }),
  ]);
  const stageSnapshotHashes = Object.fromEntries(
    privatePairs.flatMap((pair) =>
      pair.stages.map((stage) => [`${pair.agent}:${stage}`, pair.pair_hash] as const),
    ),
  );
  if (
    sortedObjectJson(privatePairs) !== sortedObjectJson(manifest.prompt_pairs) ||
    sortedObjectJson(fallbackPairs) !== sortedObjectJson(fallback.prompt_pairs) ||
    sortedObjectJson(stageSnapshotHashes) !== sortedObjectJson(manifest.stage_snapshot_hashes)
  ) {
    throw new Error("prompt_release_baseline_prompt_closure_mismatch");
  }
  const registry = new ActivePromptReleaseRegistry(opts.registryRoot);
  await registry.provisionBaseline(manifest, {
    operator: opts.approvedBy,
    reason: opts.reason.trim(),
  });
  return manifest;
}

export async function startPromptReleaseCanary(opts: {
  registryRoot: string;
  releaseId: string;
  approvedBy: string;
  reason: string;
  trafficPercent: number;
  deps?: PromptReleaseManagerDependencies;
}): Promise<ActivePromptReleaseManifest> {
  assertAuthorizedOperator(opts.approvedBy);
  if (!opts.reason.trim()) throw new Error("prompt_release_approval_reason_required");
  if (!(opts.trafficPercent > 0 && opts.trafficPercent < 100)) {
    throw new Error("prompt_release_canary_traffic_invalid");
  }
  const registry = new ActivePromptReleaseRegistry(opts.registryRoot);
  const previous = await registry.load(opts.releaseId);
  if (!previous) throw new Error("prompt_release_not_found");
  if (!previous.base_release_id) throw new Error("prompt_release_canary_baseline_required");
  const baseline = await registry.resolveActive();
  if (!baseline || baseline.release_id !== previous.base_release_id) {
    throw new Error("prompt_release_canary_baseline_mismatch");
  }
  if (previous.lifecycle_state === "canary") {
    if (
      previous.approved_by !== opts.approvedBy ||
      previous.activation_scope.traffic_percent !== opts.trafficPercent
    ) {
      throw new Error("prompt_release_canary_retry_conflict");
    }
    await registry.transition(previous, {
      audit: { operator: opts.approvedBy, reason: opts.reason.trim() },
    });
    return previous;
  }
  if (previous.lifecycle_state !== "staged") {
    throw new Error(`prompt_release_canary_state_invalid:${previous.lifecycle_state}`);
  }
  const next: ActivePromptReleaseManifest = {
    ...previous,
    lifecycle_state: "canary",
    activation_scope: { ...previous.activation_scope, traffic_percent: opts.trafficPercent },
    approved_by: opts.approvedBy,
    canary_started_at: now(opts.deps ?? {}),
  };
  await registry.transition(next, {
    audit: { operator: opts.approvedBy, reason: opts.reason.trim() },
  });
  return next;
}

export async function activatePromptRelease(opts: {
  registryRoot: string;
  releaseId: string;
  approvedBy: string;
  reason: string;
  sloArtifact: PromptReleaseCanarySloArtifact;
  eventJournalPath?: string;
  codeRepo?: string;
  deps?: PromptReleaseManagerDependencies;
}): Promise<ActivePromptReleaseManifest> {
  assertAuthorizedOperator(opts.approvedBy);
  if (!opts.reason.trim()) throw new Error("prompt_release_activation_reason_required");
  const registry = new ActivePromptReleaseRegistry(opts.registryRoot);
  const previous = await registry.load(opts.releaseId);
  if (!previous) throw new Error("prompt_release_not_found");
  if (previous.approved_by !== opts.approvedBy) {
    throw new Error("prompt_release_activation_operator_mismatch");
  }
  await assertCleanCodeCheckout(opts.codeRepo ?? findRepoRoot(), previous.code_commit);
  await assertExecutionBehaviorBindingAtCommit({
    repo: opts.codeRepo ?? findRepoRoot(),
    commit: previous.code_commit,
    promptCommit: previous.prompt_commit,
    binding: previous.execution_behavior_release,
    deps: opts.deps ?? {},
  });
  const closure = await loadPromptReleaseClosureAtCommit({
    repo: opts.codeRepo ?? findRepoRoot(),
    commit: previous.code_commit,
  });
  if (
    closure.catalog_hash !== previous.catalog_hash ||
    closure.schema_hash !== previous.schema_hash ||
    closure.contract_hash !== previous.evaluation_contract_hash
  ) {
    throw new Error("prompt_release_local_contract_closure_drift");
  }
  const sloArtifact = PromptReleaseCanarySloArtifactSchema.parse(opts.sloArtifact);
  const expectedCanaryTraffic =
    previous.lifecycle_state === "active"
      ? previous.runtime_slo_evidence?.traffic_percent
      : previous.activation_scope.traffic_percent;
  if (
    sloArtifact.release_id !== previous.release_id ||
    sloArtifact.account_mode !== previous.activation_scope.account_mode ||
    sloArtifact.traffic_percent !== expectedCanaryTraffic ||
    sloArtifact.canary_started_at !== previous.canary_started_at ||
    sloArtifact.stage_snapshot_hashes_hash !==
      stageSnapshotHashesHash(previous.stage_snapshot_hashes)
  ) {
    throw new Error("prompt_release_canary_slo_evidence_mismatch");
  }
  const eventJournalPath =
    opts.eventJournalPath?.trim() || process.env.MOSAIC_PROMPT_CANARY_EVENT_LOG?.trim();
  if (!eventJournalPath) throw new Error("prompt_release_canary_event_log_required");
  const rebuiltSloArtifact = buildPromptReleaseCanarySloArtifact({
    releaseId: previous.release_id,
    accountMode: previous.activation_scope.account_mode,
    trafficPercent: expectedCanaryTraffic as number,
    canaryStartedAt: previous.canary_started_at as string,
    observationEndedAt: sloArtifact.observation_ended_at,
    stageSnapshotHashes: previous.stage_snapshot_hashes,
    records: await new PromptReleaseCanaryEventJournal(eventJournalPath).read(),
  });
  if (sortedObjectJson(rebuiltSloArtifact) !== sortedObjectJson(sloArtifact)) {
    throw new Error("prompt_release_canary_slo_journal_closure_mismatch");
  }
  const runtimeSloSummary: RuntimeSloSummary = {
    ...sloArtifact.measurements,
    passed: promptReleaseRuntimeSloPasses({ ...sloArtifact.measurements, passed: false }),
  };
  if (!runtimeSloSummary.passed) throw new Error("prompt_release_runtime_slo_failed");
  const runtimeSloEvidence: NonNullable<ActivePromptReleaseManifest["runtime_slo_evidence"]> = {
    schema_version: "prompt_release_canary_slo_evidence_v2",
    release_id: sloArtifact.release_id,
    account_mode: sloArtifact.account_mode,
    traffic_percent: sloArtifact.traffic_percent,
    canary_started_at: sloArtifact.canary_started_at,
    observation_ended_at: sloArtifact.observation_ended_at,
    eligible_event_count: sloArtifact.eligible_event_count,
    excluded_event_count: sloArtifact.excluded_event_count,
    excluded_count_by_reason: sloArtifact.excluded_count_by_reason,
    event_set_hash: sloArtifact.event_set_hash,
    journal_closure_hash: sloArtifact.journal_closure_hash,
    journal_record_count: sloArtifact.journal_record_count,
    stage_snapshot_hashes_hash: sloArtifact.stage_snapshot_hashes_hash,
    aggregator_id: sloArtifact.aggregator_id,
    aggregator_version: sloArtifact.aggregator_version,
    artifact_hash: sloArtifact.artifact_hash,
  };
  if (previous.lifecycle_state === "active") {
    if (
      sortedObjectJson(previous.runtime_slo_summary) !== sortedObjectJson(runtimeSloSummary) ||
      sortedObjectJson(previous.runtime_slo_evidence) !== sortedObjectJson(runtimeSloEvidence)
    ) {
      throw new Error("prompt_release_activation_retry_conflict");
    }
    await registry.transition(previous, {
      expectedBaseReleaseId: previous.base_release_id,
      audit: { operator: opts.approvedBy, reason: opts.reason.trim() },
    });
    return previous;
  }
  if (previous.lifecycle_state !== "canary") {
    throw new Error(`prompt_release_activation_state_invalid:${previous.lifecycle_state}`);
  }
  const activatedAt = now(opts.deps ?? {});
  if (
    !previous.canary_started_at ||
    Date.parse(activatedAt) <= Date.parse(previous.canary_started_at)
  ) {
    throw new Error("prompt_release_canary_window_invalid");
  }
  const next: ActivePromptReleaseManifest = {
    ...previous,
    lifecycle_state: "active",
    activation_scope: { ...previous.activation_scope, traffic_percent: 100 },
    canary_ended_at: activatedAt,
    runtime_slo_summary: runtimeSloSummary,
    runtime_slo_evidence: runtimeSloEvidence,
    activated_at: activatedAt,
  };
  await registry.transition(next, {
    expectedBaseReleaseId: previous.base_release_id,
    audit: { operator: opts.approvedBy, reason: opts.reason.trim() },
  });
  return next;
}

export async function rollbackPromptRelease(opts: {
  registryRoot: string;
  releaseId: string;
  approvedBy: string;
  reason: string;
  deps?: PromptReleaseManagerDependencies;
}): Promise<ActivePromptReleaseManifest> {
  assertAuthorizedOperator(opts.approvedBy);
  if (!opts.reason.trim()) throw new Error("prompt_release_rollback_reason_required");
  const registry = new ActivePromptReleaseRegistry(opts.registryRoot);
  const previous = await registry.load(opts.releaseId);
  if (!previous) throw new Error("prompt_release_not_found");
  if (previous.lifecycle_state === "rolled_back") {
    await registry.transition(previous, {
      audit: { operator: opts.approvedBy, reason: opts.reason.trim() },
    });
    return previous;
  }
  if (previous.lifecycle_state !== "canary" && previous.lifecycle_state !== "active") {
    throw new Error(`prompt_release_rollback_state_invalid:${previous.lifecycle_state}`);
  }
  const next: ActivePromptReleaseManifest = {
    ...previous,
    lifecycle_state: "rolled_back",
    rolled_back_at: now(opts.deps ?? {}),
  };
  await registry.transition(next, {
    audit: { operator: opts.approvedBy, reason: opts.reason.trim() },
  });
  return next;
}
