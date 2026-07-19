import { execFile } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { clearPrivateKnotRuntime } from "../agents/helpers/private_knot_boundary.js";
import { checkPrivateKnotPromptBoundary } from "../agents/prompts/private_knot_prompt_checker.js";
import {
  type ActivePromptReleaseManifest,
  ActivePromptReleaseManifestSchema,
  assertReleasePromptStageClosure,
  promptReleaseRuntimeSloPasses,
  releasePromptSetHash,
} from "../agents/prompts/prompt_release_contract.js";
import {
  buildReleasePromptPairsAtCommit,
  loadPromptReleaseClosureAtCommit,
  promptPairVersionShaAtCommit,
} from "../agents/prompts/release_prompt_loader.js";
import type { RuntimeAgentSpec } from "../agents/prompts/runtime_agent_spec.js";
import { RUNTIME_AGENT_SPECS } from "../agents/prompts/runtime_agent_spec.js";
import { findRepoRoot } from "../bridge/python.js";
import type { PromptReleaseCheckResult } from "../bridge/types.js";
import { initializePrivateKnotRuntime } from "./private_knot_runtime.js";
import {
  buildPromptReleaseCanarySloArtifact,
  PromptReleaseCanaryEventJournal,
  type PromptReleaseCanarySloArtifact,
  PromptReleaseCanarySloArtifactSchema,
  stageSnapshotHashesHash,
} from "./prompt_release_canary_slo.js";
import { ActivePromptReleaseRegistry } from "./release_registry.js";

const SHA256 = /^sha256:[0-9a-f]{64}$/;

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

type RuntimeSloSummary = NonNullable<ActivePromptReleaseManifest["runtime_slo_summary"]>;

interface CandidateCheckOptions {
  repo: string;
  commit: string;
  cohort: string;
  source: "private" | "bundled";
  privateRuntimeRepo: string;
  privateRuntimeCommit: string;
}

export interface PromptReleaseCandidateCheckResult {
  snapshotHashes: Readonly<Record<string, string>>;
}

export interface PromptReleaseManagerDependencies {
  specs?: ReadonlyArray<RuntimeAgentSpec>;
  checkCandidate?: (opts: CandidateCheckOptions) => Promise<PromptReleaseCandidateCheckResult>;
  now?: () => string;
}

export interface StagePromptReleaseOptions {
  registryRoot: string;
  releaseId: string;
  verification: PromptReleaseCheckResult;
  privatePromptRepo: string;
  codeRepo?: string;
  cohort: string;
  accountMode: "paper" | "backtest" | "live";
  approvalPolicyId: "domain_release_manual_v1" | "decision_release_manual_v1";
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

async function withDetachedWorktree<T>(
  repo: string,
  commit: string,
  action: (root: string) => Promise<T>,
): Promise<T> {
  const parent = await mkdtemp(join(tmpdir(), "mosaic-prompt-release-"));
  const worktree = join(parent, "candidate");
  let added = false;
  try {
    await runGit(repo, ["worktree", "add", "--detach", worktree, commit]);
    added = true;
    return await action(worktree);
  } finally {
    if (added) await runGit(repo, ["worktree", "remove", "--force", worktree]).catch(() => null);
    await rm(parent, { recursive: true, force: true });
  }
}

async function checkCandidateAtCommit(
  opts: CandidateCheckOptions,
): Promise<PromptReleaseCandidateCheckResult> {
  const check = async (promptRoot: string, privateRuntimeRoot: string) => {
    try {
      await initializePrivateKnotRuntime({ required: true, privateRoot: privateRuntimeRoot });
      const report = await checkPrivateKnotPromptBoundary({
        cohort: opts.cohort,
        ...(opts.source === "private"
          ? { privatePromptsRoot: join(promptRoot, "prompts", "mosaic") }
          : { promptsRoot: join(promptRoot, "prompts", "mosaic") }),
        requirePrivateKnot: true,
        enabledAgentStages: new Set(["*"]),
      });
      if (
        !report.ready ||
        report.bundled_fallback_agent_stages.length > 0 ||
        report.unavailable_agent_stages.length > 0
      ) {
        const failures = report.rows
          .filter((row) => !row.ready)
          .flatMap((row) => row.reasons.map((reason) => `${row.agent}:${row.stage}:${reason}`));
        throw new Error(`prompt_release_candidate_check_failed:${failures.slice(0, 10).join("|")}`);
      }
      return {
        snapshotHashes: Object.fromEntries(
          report.rows.map((row) => [`${row.agent}:${row.stage}`, row.snapshot_hash ?? ""]),
        ),
      };
    } finally {
      clearPrivateKnotRuntime();
    }
  };
  return withDetachedWorktree(opts.repo, opts.commit, async (promptRoot) => {
    if (opts.repo === opts.privateRuntimeRepo && opts.commit === opts.privateRuntimeCommit) {
      return check(promptRoot, promptRoot);
    }
    return withDetachedWorktree(
      opts.privateRuntimeRepo,
      opts.privateRuntimeCommit,
      (privateRuntimeRoot) => check(promptRoot, privateRuntimeRoot),
    );
  });
}

function requirePin(
  verification: PromptReleaseCheckResult,
  cohort: string,
): {
  agent: string;
  promptCommit: string;
  codeCommit: string;
  promptSha: string;
  keepDecisionHash: string;
  versionId: number;
  mutationId: string;
  experimentId: string;
  evaluationResultHash: string;
  transactionManifestHash: string;
} {
  if (!verification.ready) throw new Error("prompt_release_verification_not_ready");
  const pin = verification.pin;
  if (pin.cohort !== cohort) throw new Error("prompt_release_verification_cohort_mismatch");
  if (pin.prompt_repo_id !== "private") {
    throw new Error("prompt_release_verification_not_private");
  }
  const promptCommit = pin.prompt_commit_hash?.trim() ?? "";
  const codeCommit = pin.code_commit_hash?.trim() ?? "";
  const promptSha = pin.prompt_sha256?.trim() ?? "";
  const keepDecisionHash = pin.keep_decision_hash?.trim() ?? "";
  const mutationId = pin.mutation_id?.trim() ?? "";
  const experimentId = pin.experiment_id?.trim() ?? "";
  const evaluationResultHash = pin.evaluation_result_hash?.trim() ?? "";
  const transactionManifestHash = pin.transaction_manifest_hash?.trim() ?? "";
  if (!promptCommit || !codeCommit || !/^[0-9a-f]{64}$/.test(promptSha)) {
    throw new Error("prompt_release_verification_pin_incomplete");
  }
  if (
    !SHA256.test(keepDecisionHash) ||
    !Number.isInteger(pin.version_id) ||
    pin.version_id < 1 ||
    !mutationId ||
    !experimentId ||
    !SHA256.test(evaluationResultHash) ||
    !SHA256.test(transactionManifestHash)
  ) {
    throw new Error("prompt_release_evaluation_trace_incomplete");
  }
  return {
    agent: pin.agent,
    promptCommit,
    codeCommit,
    promptSha,
    keepDecisionHash,
    versionId: pin.version_id,
    mutationId,
    experimentId,
    evaluationResultHash,
    transactionManifestHash,
  };
}

function now(deps: PromptReleaseManagerDependencies): string {
  return deps.now?.() ?? new Date().toISOString();
}

function sortedObjectJson(value: object | null): string {
  if (!value) return "null";
  return JSON.stringify(
    Object.fromEntries(Object.entries(value).sort(([left], [right]) => left.localeCompare(right))),
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
  const pin = requirePin(opts.verification, opts.cohort);
  if (
    ["cro", "alpha_discovery", "autonomous_execution", "cio"].includes(pin.agent) &&
    opts.approvalPolicyId !== "decision_release_manual_v1"
  ) {
    throw new Error("prompt_release_decision_policy_required");
  }
  const [promptCommit, codeCommit] = await Promise.all([
    fullCommit(opts.privatePromptRepo, pin.promptCommit),
    fullCommit(codeRepo, pin.codeCommit),
  ]);
  if (promptCommit !== pin.promptCommit || codeCommit !== pin.codeCommit) {
    throw new Error("prompt_release_requires_full_commit_ids");
  }
  await assertCleanCodeCheckout(codeRepo, codeCommit);
  const candidateCheck = deps.checkCandidate ?? checkCandidateAtCommit;
  const privateCheck = await candidateCheck({
    repo: opts.privatePromptRepo,
    commit: promptCommit,
    cohort: opts.cohort,
    source: "private",
    privateRuntimeRepo: opts.privatePromptRepo,
    privateRuntimeCommit: promptCommit,
  });
  const promptPairs = await buildReleasePromptPairsAtCommit({
    repo: opts.privatePromptRepo,
    commit: promptCommit,
    cohort: opts.cohort,
    specs,
  });
  assertReleasePromptStageClosure(
    {
      schema_version: "active_prompt_release_manifest_v1",
      release_id: opts.releaseId,
      base_release_id: null,
      lifecycle_state: "staged",
      prompt_commit: promptCommit,
      code_commit: codeCommit,
      prompt_hash: releasePromptSetHash(promptPairs),
      prompt_pairs: promptPairs,
      stage_snapshot_hashes: privateCheck.snapshotHashes,
      catalog_hash: `sha256:${"0".repeat(64)}`,
      schema_hash: `sha256:${"0".repeat(64)}`,
      evaluation_contract_hash: `sha256:${"0".repeat(64)}`,
      keep_decision_hash: pin.keepDecisionHash,
      keep_decision_state: "kept",
      release_evidence: {
        version_id: pin.versionId,
        mutation_id: pin.mutationId,
        experiment_id: pin.experimentId,
        mutated_agent: pin.agent,
        evaluation_result_hash: pin.evaluationResultHash,
        transaction_manifest_hash: pin.transactionManifestHash,
        prompt_pair_sha256: pin.promptSha,
      },
      activation_scope: { cohort: opts.cohort, account_mode: opts.accountMode, traffic_percent: 0 },
      approval_policy_id: opts.approvalPolicyId,
      approved_by: null,
      canary_started_at: null,
      canary_ended_at: null,
      runtime_slo_summary: null,
      runtime_slo_evidence: null,
      rollback_triggers: ["pending"],
      previous_approved_release_id: null,
      bundled_fallback: null,
      created_at: now(deps),
      activated_at: null,
      rolled_back_at: null,
    },
    specs.flatMap((spec) =>
      spec.stages.map((stage) => ({ agent: spec.agent, layer: spec.layer, stage: stage.stage })),
    ),
  );
  const mutatedPair = promptPairs.find((pair) => pair.agent === pin.agent);
  if (!mutatedPair) throw new Error("prompt_release_mutated_agent_pair_missing");
  if (
    (await promptPairVersionShaAtCommit({
      repo: opts.privatePromptRepo,
      commit: promptCommit,
      pair: mutatedPair,
    })) !== pin.promptSha
  ) {
    throw new Error("prompt_release_verification_prompt_sha_mismatch");
  }

  const closure = await loadPromptReleaseClosureAtCommit({ repo: codeRepo, commit: codeCommit });
  const fallbackCheck = await candidateCheck({
    repo: codeRepo,
    commit: codeCommit,
    cohort: opts.cohort,
    source: "bundled",
    privateRuntimeRepo: opts.privatePromptRepo,
    privateRuntimeCommit: promptCommit,
  });
  if (
    sortedObjectJson(privateCheck.snapshotHashes) !== sortedObjectJson(fallbackCheck.snapshotHashes)
  ) {
    throw new Error("prompt_release_bundled_fallback_snapshot_mismatch");
  }
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

  const registry = new ActivePromptReleaseRegistry(opts.registryRoot);
  const pointer = await registry.pointer();
  const createdAt = now(deps);
  const manifest: ActivePromptReleaseManifest = {
    schema_version: "active_prompt_release_manifest_v1",
    release_id: opts.releaseId,
    base_release_id: pointer.current_release_id,
    lifecycle_state: "staged",
    prompt_commit: promptCommit,
    code_commit: codeCommit,
    prompt_hash: releasePromptSetHash(promptPairs),
    prompt_pairs: promptPairs,
    stage_snapshot_hashes: privateCheck.snapshotHashes,
    catalog_hash: closure.catalog_hash,
    schema_hash: closure.schema_hash,
    evaluation_contract_hash: closure.contract_hash,
    keep_decision_hash: pin.keepDecisionHash,
    keep_decision_state: "kept",
    release_evidence: {
      version_id: pin.versionId,
      mutation_id: pin.mutationId,
      experiment_id: pin.experimentId,
      mutated_agent: pin.agent,
      evaluation_result_hash: pin.evaluationResultHash,
      transaction_manifest_hash: pin.transactionManifestHash,
      prompt_pair_sha256: pin.promptSha,
    },
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
  await registry.stage(manifest);
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
  const candidateCheck = opts.deps?.checkCandidate ?? checkCandidateAtCommit;
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
  // The adapter is process-global, so candidate checks must not race a worktree
  // removal against another check that is still reading the same pinned runtime.
  const privateCheck = await candidateCheck({
    repo: opts.privatePromptRepo,
    commit: promptCommit,
    cohort: manifest.activation_scope.cohort,
    source: "private",
    privateRuntimeRepo: opts.privatePromptRepo,
    privateRuntimeCommit: promptCommit,
  });
  const fallbackCheck = await candidateCheck({
    repo: codeRepo,
    commit: fallback.prompt_commit,
    cohort: manifest.activation_scope.cohort,
    source: "bundled",
    privateRuntimeRepo: opts.privatePromptRepo,
    privateRuntimeCommit: promptCommit,
  });
  if (
    sortedObjectJson(privatePairs) !== sortedObjectJson(manifest.prompt_pairs) ||
    sortedObjectJson(fallbackPairs) !== sortedObjectJson(fallback.prompt_pairs) ||
    sortedObjectJson(privateCheck.snapshotHashes) !==
      sortedObjectJson(manifest.stage_snapshot_hashes) ||
    sortedObjectJson(fallbackCheck.snapshotHashes) !==
      sortedObjectJson(manifest.stage_snapshot_hashes)
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
  if (!previous.canary_started_at || activatedAt <= previous.canary_started_at) {
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
