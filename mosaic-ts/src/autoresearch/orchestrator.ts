/**
 * Autoresearch orchestration loop (Plan 11.5 Phase 4E).
 *
 * Ties together trigger/mutate/commit/eval/decide into a single automated
 * cycle. The orchestrator:
 *   1. Triggers a new prompt version (selects agent via constraints).
 *   2. Generates a mutation via the mutator LLM call.
 *   3. Commits the rewritten prompt on the feature branch.
 *   4. Records the mutation in the autoresearch store.
 *   5. Prepares a worktree for backtest evaluation.
 *   6. Attempts evaluation (may require backtest-fill to run separately).
 *   7. Cleans up the worktree.
 *
 * In dry-run mode, step 3+ are skipped (mutation is generated but not
 * persisted).
 */

import { createHash } from "node:crypto";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import { isResearchKnobsEnabled } from "../agents/helpers/research_knobs.js";
import { LAYER_BY_AGENT } from "../agents/prompts/cohorts.js";
import type { MutationTransactionManifest } from "../agents/prompts/prompt_release_contract.js";
import type { AutoresearchMissingRun, BridgeApi, PromptWriteResult } from "../bridge/types.js";
import { redactSensitiveText } from "../security/redaction.js";
import {
  appendKnobMutationMetadataLog,
  assignDomainEvaluationAttemptIndex,
  buildKnobMutationMetadata,
  type KnobMutationMetadata,
  mutate,
  mutateResearchKnobs,
  type ResearchKnobPromptMutation,
} from "./mutator.js";
import {
  PromptMutationRecoveryDescriptorStore,
  reconcilePendingPromptMutationTransactions,
  reconcileTerminalPromptMutationLeases,
} from "./prompt_mutation_recovery.js";
import {
  MutationPathLeaseRegistry,
  type MutationRepositoryAdapter,
  MutationTransactionJournal,
  PromptMutationTransactionCoordinator,
} from "./transaction_coordinator.js";

export interface AutoresearchCycleOptions {
  cohort: string;
  evalDays?: number;
  maxMutations?: number;
  dryRun?: boolean;
  forceAgent?: string;
  /** Use the deterministic canned mutation (Plan §11.5 4F --fake-llm smoke). */
  fakeLlm?: boolean;
  mutationMode?: "auto" | "knob_patch" | "prompt_rewrite";
  deps: {
    llm: BaseChatModel;
    api: BridgeApi;
  };
  onLog?: (msg: string) => void;
}

export interface MutationResult {
  agent: string;
  version_id: number | null;
  status:
    | "kept"
    | "reverted"
    | "eligible_for_promotion"
    | "invalid"
    | "dry_run"
    | "needs_fill"
    | "incompatible"
    | "error";
  delta_sharpe?: number;
  summary?: string;
  error?: string;
  fill_commands?: string[];
}

export interface CycleResult {
  mutations: MutationResult[];
}

function shellQuote(value: string): string {
  if (/^[A-Za-z0-9_./:@+=,-]+$/.test(value)) return value;
  return `'${value.replaceAll("'", "'\\''")}'`;
}

function knobMutationLogPath(): string | null {
  const explicit = process.env.MOSAIC_KNOB_MUTATION_LOG?.trim();
  if (explicit) return explicit;
  const repo =
    process.env.MOSAIC_PROMPTS_REPO?.trim() ?? process.env.MOSAIC_PRIVATE_PROMPT_REPO?.trim();
  return repo ? join(repo, "mutation_patches", "knob_mutations.jsonl") : null;
}

function transactionRoot(): string {
  const explicit = process.env.MOSAIC_PROMPT_MUTATION_TRANSACTION_DIR?.trim();
  if (explicit) return explicit;
  const root =
    process.env.MOSAIC_REPO_ROOT?.trim() ?? fileURLToPath(new URL("../../../", import.meta.url));
  return join(root, ".mosaic", "autoresearch", "prompt-mutation-transactions");
}

function sha256(value: string): string {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

function stableJsonHash(value: unknown): string {
  return sha256(JSON.stringify(value));
}

function promptPairSha256(
  agent: string,
  cohort: string,
  contents: { zh: string; en: string },
): string {
  const layer = LAYER_BY_AGENT[agent];
  if (!layer) throw new Error(`unknown prompt agent: ${agent}`);
  const files = {
    [`prompts/mosaic/${cohort}/${layer}/${agent}.zh.md`]: contents.zh,
    [`prompts/mosaic/${cohort}/${layer}/${agent}.en.md`]: contents.en,
  };
  const digest = createHash("sha256");
  for (const [path, content] of Object.entries(files).sort(([left], [right]) =>
    left.localeCompare(right),
  )) {
    digest.update(path);
    digest.update("\0");
    digest.update(content);
    digest.update("\0");
  }
  return digest.digest("hex");
}

function isResearchKnobPromptMutation(value: unknown): value is ResearchKnobPromptMutation {
  return (
    value !== null &&
    typeof value === "object" &&
    "knob_mutation" in value &&
    "base_knobs" in value &&
    "new_knobs" in value
  );
}

async function privatePromptBaseCommit(
  api: BridgeApi,
  cohort: string,
  agent: string,
  fallback: string,
): Promise<string> {
  if (typeof api.promptsPreflight !== "function") return fallback;
  try {
    const preflight = await api.promptsPreflight({ cohort, agents: [agent], langs: ["zh", "en"] });
    const revision = preflight.source_status.prompt_repo_revision;
    return revision.length >= 7 ? revision : fallback;
  } catch {
    return fallback;
  }
}

async function executeKnobMutationTransaction(opts: {
  api: BridgeApi;
  versionId: number;
  branch: string;
  agent: string;
  cohort: string;
  codeCommit: string;
  summary: string;
  mutation: ResearchKnobPromptMutation;
  metadata: KnobMutationMetadata;
}): Promise<{
  writeResult: PromptWriteResult;
  metadata: KnobMutationMetadata;
  coordinator: PromptMutationTransactionCoordinator;
}> {
  if (opts.metadata.mutation_kind === "generic_knob" && !opts.mutation.governance_registry_update) {
    throw new Error("generic knob mutation requires authoritative governance write-back");
  }
  if (opts.metadata.mutation_kind === "domain_knob" && !opts.mutation.domain_registry_update) {
    throw new Error("domain knob mutation requires authoritative domain write-back");
  }
  const layer = LAYER_BY_AGENT[opts.agent];
  if (!layer) throw new Error(`unknown prompt agent: ${opts.agent}`);
  const promptBaseCommit = await privatePromptBaseCommit(
    opts.api,
    opts.cohort,
    opts.agent,
    opts.codeCommit,
  );
  const promptPaths = {
    zh: `prompts/mosaic/${opts.cohort}/${layer}/${opts.agent}.zh.md`,
    en: `prompts/mosaic/${opts.cohort}/${layer}/${opts.agent}.en.md`,
  };
  const files: MutationTransactionManifest["components"][number]["files"] = [
    {
      path: promptPaths.zh,
      old_hash: opts.mutation.prompt_file_hashes.zh.old_sha256,
      new_hash: opts.mutation.prompt_file_hashes.zh.new_sha256,
      staging_path_hash: stableJsonHash({
        mutation_id: opts.metadata.mutation_id,
        path: promptPaths.zh,
        new_hash: opts.mutation.prompt_file_hashes.zh.new_sha256,
      }),
    },
    {
      path: promptPaths.en,
      old_hash: opts.mutation.prompt_file_hashes.en.old_sha256,
      new_hash: opts.mutation.prompt_file_hashes.en.new_sha256,
      staging_path_hash: stableJsonHash({
        mutation_id: opts.metadata.mutation_id,
        path: promptPaths.en,
        new_hash: opts.mutation.prompt_file_hashes.en.new_sha256,
      }),
    },
  ];
  if (opts.mutation.domain_registry_update) {
    files.push({
      path: opts.mutation.domain_registry_update.relative_path,
      old_hash: opts.mutation.domain_registry_update.old_sha256,
      new_hash: opts.mutation.domain_registry_update.new_sha256,
      staging_path_hash: stableJsonHash({
        mutation_id: opts.metadata.mutation_id,
        path: opts.mutation.domain_registry_update.relative_path,
        new_hash: opts.mutation.domain_registry_update.new_sha256,
      }),
    });
  }
  if (opts.mutation.governance_registry_update) {
    files.push({
      path: opts.mutation.governance_registry_update.relative_path,
      old_hash: opts.mutation.governance_registry_update.old_sha256,
      new_hash: opts.mutation.governance_registry_update.new_sha256,
      staging_path_hash: stableJsonHash({
        mutation_id: opts.metadata.mutation_id,
        path: opts.mutation.governance_registry_update.relative_path,
        new_hash: opts.mutation.governance_registry_update.new_sha256,
      }),
    });
  }
  const root = transactionRoot();
  const logPath = knobMutationLogPath();
  if (!logPath) throw new Error("private knob mutation metadata log is not configured");
  const promptSha = promptPairSha256(opts.agent, opts.cohort, {
    zh: opts.mutation.zh_prompt,
    en: opts.mutation.en_prompt,
  });
  const recoveryDescriptorHash = await new PromptMutationRecoveryDescriptorStore(root).writeOnce({
    schema_version: "prompt_mutation_recovery_v1",
    transaction_id: opts.metadata.transaction_id,
    mutation_id: opts.metadata.mutation_id,
    version_id: opts.versionId,
    agent: opts.agent,
    cohort: opts.cohort,
    branch: opts.branch,
    summary: opts.summary,
    prompt_sha256: promptSha,
    code_commit_hash: opts.codeCommit,
    metadata_log_path: logPath,
    mutation_metadata: opts.metadata,
  });
  const created: MutationTransactionManifest = {
    schema_version: "prompt_mutation_transaction_v1",
    mutation_id: opts.metadata.mutation_id,
    transaction_id: opts.metadata.transaction_id,
    experiment_id: opts.metadata.experiment_id,
    state: "created",
    recovery_state: "not_needed",
    base_release_id: process.env.MOSAIC_ACTIVE_PROMPT_RELEASE_ID?.trim() || "release-uninitialized",
    catalog_hash: opts.metadata.catalog_hash,
    schema_hash: opts.metadata.schema_hash,
    evaluation_contract_hash: opts.metadata.evaluation_contract_hash,
    recovery_descriptor_hash: recoveryDescriptorHash,
    target_paths: [...opts.metadata.changed_paths],
    components: [
      {
        repo_id: "MOSAIC-Prompts",
        base_commit: promptBaseCommit,
        new_commit: null,
        candidate_ref: `refs/heads/${opts.branch}`,
        prepare_status: "pending",
        files,
      },
    ],
    metadata_log: {
      path: "mutation_patches/knob_mutations.jsonl",
      entry_hash: stableJsonHash(opts.metadata),
      appended: false,
    },
    created_at: opts.metadata.created_at,
    prepared_at: null,
    committed_at: null,
    aborted_at: null,
    recovery_decision: null,
  };
  const coordinator = new PromptMutationTransactionCoordinator(
    new MutationTransactionJournal(root),
    new MutationPathLeaseRegistry(root),
  );
  let writeResult: PromptWriteResult | null = null;
  const expectedHashes = Object.fromEntries(files.map((file) => [file.path, file.new_hash]));
  const adapter: MutationRepositoryAdapter = {
    repoId: "MOSAIC-Prompts",
    prepare: async () => undefined,
    commit: async () => {
      writeResult = await opts.api.promptsWrite({
        agent: opts.agent,
        cohort: opts.cohort,
        contents: { zh: opts.mutation.zh_prompt, en: opts.mutation.en_prompt },
        ...(opts.mutation.domain_registry_update || opts.mutation.governance_registry_update
          ? {
              extra_files: {
                ...(opts.mutation.domain_registry_update
                  ? {
                      [opts.mutation.domain_registry_update.relative_path]:
                        opts.mutation.domain_registry_update.content,
                    }
                  : {}),
                ...(opts.mutation.governance_registry_update
                  ? {
                      [opts.mutation.governance_registry_update.relative_path]:
                        opts.mutation.governance_registry_update.content,
                    }
                  : {}),
              },
            }
          : {}),
        target: "private_git",
        branch: opts.branch,
        message: `autoresearch: ${opts.summary}`,
      });
      const commit = writeResult.prompt_commit_hash ?? writeResult.commit_hash;
      if (!commit) throw new Error("private prompt mutation returned no commit hash");
      return commit;
    },
    inspect: async () => {
      if (typeof opts.api.promptsCandidateState === "function") {
        const state = await opts.api.promptsCandidateState({
          branch: opts.branch,
          expected_hashes: expectedHashes,
        });
        return {
          candidate_visible: state.candidate_visible && state.hashes_match,
          new_commit: state.new_commit,
        };
      }
      const commit = writeResult?.prompt_commit_hash ?? writeResult?.commit_hash ?? null;
      return { candidate_visible: commit !== null, new_commit: commit };
    },
    abort: async () => {
      if (typeof opts.api.promptsAbortCandidate === "function") {
        await opts.api.promptsAbortCandidate({ branch: opts.branch });
      }
    },
  };
  let durableMetadata = opts.metadata;
  await coordinator.execute(created, [adapter], {
    appendOnce: async (manifest, manifestHash) => {
      const commit = manifest.components[0]?.new_commit;
      if (!commit) throw new Error("committed prompt transaction lacks candidate commit");
      if (writeResult?.prompt_sha256 && writeResult.prompt_sha256 !== promptSha) {
        throw new Error("private prompt mutation returned a mismatched prompt digest");
      }
      durableMetadata = { ...opts.metadata, transaction_manifest_hash: manifestHash };
      await opts.api.autoresearchRecordMutation({
        version_id: opts.versionId,
        commit_hash: commit,
        summary: opts.summary,
        prompt_repo_id: writeResult?.prompt_repo_id ?? "private",
        prompt_base_commit_hash: writeResult?.prompt_base_commit_hash ?? promptBaseCommit,
        prompt_sha256: promptSha,
        code_commit_hash: opts.codeCommit,
        mutation_metadata: durableMetadata,
      });
      await appendKnobMutationMetadataLog({ logPath, metadata: durableMetadata });
    },
  });
  if (!writeResult) {
    const committed = await new MutationTransactionJournal(root).findByMutationId(
      opts.metadata.mutation_id,
    );
    const commit = committed?.components[0]?.new_commit;
    if (!commit) throw new Error("prompt transaction committed without a candidate commit");
    writeResult = {
      target: "private_git",
      prompt_repo_id: "private",
      prompt_base_commit_hash: promptBaseCommit,
      prompt_commit_hash: commit,
      commit_hash: commit,
      prompt_sha256: promptPairSha256(opts.agent, opts.cohort, {
        zh: opts.mutation.zh_prompt,
        en: opts.mutation.en_prompt,
      }),
      branch: opts.branch,
      paths: files.map((file) => file.path),
    };
  }
  return { writeResult, metadata: durableMetadata, coordinator };
}

export function backtestFillCommand(run: AutoresearchMissingRun): string {
  const args = [
    "pnpm",
    "dev",
    "backtest-fill",
    "--cohort",
    run.cohort,
    "--start",
    run.start_date,
    "--end",
    run.end_date,
    "--prompt-commit-hash",
    run.prompt_commit_hash,
  ];
  if (run.private_prompt_commit) {
    args.push("--private-prompt-commit", run.private_prompt_commit);
  }
  if (run.prompt_repo_id) {
    args.push("--prompt-repo-id", run.prompt_repo_id);
  }
  if (run.prompt_sha256) {
    args.push("--prompt-sha256", run.prompt_sha256);
  }
  if (run.code_commit_hash) {
    args.push("--code-commit-hash", run.code_commit_hash);
  }
  return args.map(shellQuote).join(" ");
}

export async function recoverPromptMutationTransactions(
  api: BridgeApi,
  root = transactionRoot(),
): Promise<MutationTransactionManifest[]> {
  const reconciled = await reconcilePendingPromptMutationTransactions({ root, api });
  await reconcileTerminalPromptMutationLeases({ api, root });
  return reconciled;
}

export async function completePromptMutationExperiment(
  mutationId: string,
  root = transactionRoot(),
): Promise<void> {
  await new MutationPathLeaseRegistry(root).release(mutationId);
}

export async function runAutoresearchCycle(opts: AutoresearchCycleOptions): Promise<CycleResult> {
  const {
    cohort,
    // evalDays is reserved for future use when backtest-fill integration
    // allows specifying the evaluation window directly from the orchestrator.
    maxMutations = 1,
    dryRun = false,
    forceAgent,
    fakeLlm = false,
    mutationMode = "auto",
    deps,
    onLog,
  } = opts;

  const log = onLog ?? (() => {});
  const safeLog = (msg: string) => log(redactSensitiveText(msg));
  const results: MutationResult[] = [];

  const recovered = await recoverPromptMutationTransactions(deps.api);
  if (recovered.length > 0) {
    safeLog(`reconciled ${recovered.length} pending prompt mutation transaction(s)`);
  }

  for (let n = 0; n < maxMutations; n++) {
    // 1. Trigger: select agent + create pending version
    let triggerResult: Awaited<ReturnType<BridgeApi["autoresearchTrigger"]>>;
    try {
      triggerResult = await deps.api.autoresearchTrigger({
        cohort,
        ...(forceAgent ? { force_agent: forceAgent } : {}),
        ...(dryRun ? { dry_run: true } : {}),
      });
    } catch (err) {
      safeLog(`trigger blocked: ${(err as Error).message}`);
      break;
    }

    safeLog(
      `triggered: agent=${triggerResult.agent} version_id=${triggerResult.version_id} branch=${triggerResult.branch_name}`,
    );
    const cycleMutationId = `KM-${triggerResult.version_id ?? "dry"}-${Date.now()}-${n}`;

    // 2. Mutate: parameter-level research-knobs patch when enabled, otherwise legacy rewrite.
    let mutation: Awaited<ReturnType<typeof mutate>>;
    try {
      const useKnobMutation =
        mutationMode === "knob_patch" ||
        (mutationMode === "auto" && isResearchKnobsEnabled(triggerResult.agent));
      mutation = useKnobMutation
        ? await mutateResearchKnobs({
            cohort,
            agent: triggerResult.agent,
            deps: { llm: deps.llm, api: deps.api },
            mutationId: cycleMutationId,
            ...(fakeLlm ? { fakeLlm: true } : {}),
          })
        : await mutate({
            cohort,
            agent: triggerResult.agent,
            deps: { llm: deps.llm, api: deps.api },
            ...(fakeLlm ? { fakeLlm: true } : {}),
          });
    } catch (err) {
      results.push({
        agent: triggerResult.agent,
        version_id: triggerResult.version_id,
        status: "error",
        error: redactSensitiveText(`mutation failed: ${(err as Error).message}`),
      });
      continue;
    }

    safeLog(`mutated: ${mutation.modification_summary}`);
    const knobPromptMutation = isResearchKnobPromptMutation(mutation) ? mutation : null;

    // 3. Dry-run: record result without committing
    if (dryRun) {
      if (knobPromptMutation) {
        const logPath = knobMutationLogPath();
        if (logPath) {
          await appendKnobMutationMetadataLog({
            logPath,
            metadata: buildKnobMutationMetadata({
              mutationId: cycleMutationId,
              agent: triggerResult.agent,
              cohort,
              baseKnobs: knobPromptMutation.base_knobs,
              newKnobs: knobPromptMutation.new_knobs,
              mutation: knobPromptMutation.knob_mutation,
              decision: "dry_run",
            }),
          });
        }
      }
      results.push({
        agent: triggerResult.agent,
        version_id: triggerResult.version_id,
        status: "dry_run",
        summary: mutation.modification_summary,
      });
      continue;
    }

    // Past dry-run, trigger must have persisted a version row.
    const versionId = triggerResult.version_id;
    if (versionId == null) {
      results.push({
        agent: triggerResult.agent,
        version_id: null,
        status: "error",
        error: "trigger returned no version_id (non-dry-run)",
      });
      continue;
    }

    const mutationId = knobPromptMutation ? cycleMutationId : null;
    let knobMutationMetadata =
      knobPromptMutation && mutationId
        ? buildKnobMutationMetadata({
            mutationId,
            agent: triggerResult.agent,
            cohort,
            baseKnobs: knobPromptMutation.base_knobs,
            newKnobs: knobPromptMutation.new_knobs,
            mutation: knobPromptMutation.knob_mutation,
            decision: "applied",
          })
        : null;
    if (knobMutationMetadata?.evaluation_policy.preregistration) {
      const logPath = knobMutationLogPath();
      if (!logPath) {
        results.push({
          agent: triggerResult.agent,
          version_id: versionId,
          status: "error",
          error: "private knob mutation metadata log is not configured",
        });
        continue;
      }
      try {
        knobMutationMetadata = await assignDomainEvaluationAttemptIndex({
          logPath,
          metadata: knobMutationMetadata,
        });
      } catch (error) {
        results.push({
          agent: triggerResult.agent,
          version_id: versionId,
          status: "error",
          error: redactSensitiveText((error as Error).message),
        });
        continue;
      }
    }

    // 4-5. Commit and durably record the candidate. Knob mutations use the
    // transaction journal; legacy prose rewrites retain the existing path.
    let writeResult: Awaited<ReturnType<BridgeApi["promptsWrite"]>>;
    let mutationCoordinator: PromptMutationTransactionCoordinator | null = null;
    try {
      if (knobPromptMutation && knobMutationMetadata) {
        const transactional = await executeKnobMutationTransaction({
          api: deps.api,
          versionId,
          branch: triggerResult.branch_name,
          agent: triggerResult.agent,
          cohort,
          codeCommit: triggerResult.base_commit,
          summary: mutation.modification_summary,
          mutation: knobPromptMutation,
          metadata: knobMutationMetadata,
        });
        writeResult = transactional.writeResult;
        knobMutationMetadata = transactional.metadata;
        mutationCoordinator = transactional.coordinator;
      } else {
        writeResult = await deps.api.promptsWrite({
          agent: triggerResult.agent,
          cohort,
          contents: { zh: mutation.zh_prompt, en: mutation.en_prompt },
          target: "private_git",
          branch: triggerResult.branch_name,
          message: `autoresearch: ${mutation.modification_summary}`,
        });
        await deps.api.autoresearchRecordMutation({
          version_id: versionId,
          commit_hash: writeResult.prompt_commit_hash ?? writeResult.commit_hash ?? "unknown",
          summary: mutation.modification_summary,
          ...(writeResult.prompt_repo_id ? { prompt_repo_id: writeResult.prompt_repo_id } : {}),
          ...(writeResult.prompt_base_commit_hash
            ? { prompt_base_commit_hash: writeResult.prompt_base_commit_hash }
            : {}),
          ...(writeResult.prompt_sha256 ? { prompt_sha256: writeResult.prompt_sha256 } : {}),
          code_commit_hash: triggerResult.base_commit,
        });
      }
    } catch (err) {
      results.push({
        agent: triggerResult.agent,
        version_id: versionId,
        status: "error",
        error: redactSensitiveText(`write failed: ${(err as Error).message}`),
      });
      continue;
    }

    // 6. Prepare worktree for evaluation
    let worktreePath: string | undefined;
    if (writeResult.target !== "private_git") {
      try {
        const worktree = await deps.api.autoresearchPrepareWorktree({
          branch: triggerResult.branch_name,
        });
        worktreePath = worktree.path;
        safeLog("worktree ready");
      } catch (err) {
        safeLog(`worktree prep failed: ${(err as Error).message} (eval needs to run separately)`);
      }
    }

    // 7. Attempt evaluation (backtest-fill needs to run separately for full eval)
    safeLog("evaluation: backtest-fill needs to run separately for this branch");

    let evalStatus: MutationResult["status"] = "needs_fill";
    let deltaSharpe: number | undefined;
    let fillCommands: string[] | undefined;
    let evalError: string | undefined;

    try {
      // Scope evaluation to the version we just triggered, so an N-agent layer
      // does N single-version evaluations instead of N full-cohort scans
      // (§11.6 O(N²) fix). The result therefore contains at most this version.
      const evalResult = await deps.api.autoresearchEvaluatePending({
        cohort,
        version_id: versionId,
      });
      const thisEval = evalResult.results.find((r) => r.version_id === versionId);
      if (thisEval) {
        if (
          thisEval.status === "kept" ||
          thisEval.status === "reverted" ||
          thisEval.status === "eligible_for_promotion" ||
          thisEval.status === "invalid"
        ) {
          evalStatus = thisEval.status;
          deltaSharpe = thisEval.delta_sharpe;
        } else if (thisEval.status === "incompatible") {
          evalStatus = "incompatible";
          evalError = redactSensitiveText(
            thisEval.detail ?? "prompt is incompatible with current code",
          );
          safeLog(`evaluation incompatible: ${evalError}`);
        } else if (thisEval.status === "needs_fill") {
          evalStatus = "needs_fill";
          fillCommands = (thisEval.missing_runs ?? []).map(backtestFillCommand);
          for (const command of fillCommands) {
            safeLog(`backtest-fill required: ${command}`);
          }
        } else if (thisEval.status === "error") {
          evalStatus = "error";
          evalError = redactSensitiveText(thisEval.detail ?? "evaluation failed");
          safeLog(`evaluation error: ${evalError}`);
        } else {
          evalStatus = "needs_fill";
        }
      }
    } catch (err) {
      // Evaluation not ready yet or crashed; log for visibility
      evalStatus = "error";
      evalError = redactSensitiveText((err as Error).message ?? "unknown");
      safeLog(`evaluation error: ${evalError}`);
    }

    if (
      mutationCoordinator &&
      mutationId &&
      ["kept", "reverted", "invalid", "incompatible"].includes(evalStatus)
    ) {
      try {
        await mutationCoordinator.completeExperiment(mutationId);
      } catch (err) {
        safeLog(`mutation lease release failed: ${(err as Error).message}`);
      }
    }

    // 8. Cleanup worktree
    if (worktreePath) {
      try {
        await deps.api.autoresearchCleanupWorktree({ path: worktreePath });
      } catch {
        safeLog("worktree cleanup failed");
      }
    }

    // 9. Record result
    results.push({
      agent: triggerResult.agent,
      version_id: versionId,
      status: evalStatus,
      ...(deltaSharpe != null ? { delta_sharpe: deltaSharpe } : {}),
      ...(evalError ? { error: evalError } : {}),
      ...(fillCommands && fillCommands.length > 0 ? { fill_commands: fillCommands } : {}),
      summary: mutation.modification_summary,
    });
  }

  return { mutations: results };
}
