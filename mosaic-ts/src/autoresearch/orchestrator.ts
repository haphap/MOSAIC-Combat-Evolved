/**
 * Legacy prompt-rewrite diagnostic loop.
 *
 * It can create and evaluate private prompt candidates, but it has no KNOT
 * policy mutation or production-promotion edge. Those operations belong to the
 * hash-pinned private runtime.
 */

import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import type { AutoresearchMissingRun, BridgeApi } from "../bridge/types.js";
import { redactSensitiveText } from "../security/redaction.js";
import { mutate } from "./mutator.js";

export interface AutoresearchCycleOptions {
  cohort: string;
  evalDays?: number;
  maxMutations?: number;
  dryRun?: boolean;
  forceAgent?: string;
  fakeLlm?: boolean;
  mutationMode?: "auto" | "prompt_rewrite";
  simulatedNow?: string;
  promptsRoot?: string;
  basePromptCommit?: string;
  codeCommitHash?: string;
  historicalSandbox?: boolean;
  historicalRunId?: string;
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
    | "legacy_unverified"
    | "error";
  delta_sharpe?: number;
  summary?: string;
  error?: string;
  fill_commands?: string[];
  branch_name?: string;
  prompt_commit_hash?: string;
  prompt_sha256?: string;
  prompt_base_commit_hash?: string;
}

export interface CycleResult {
  namespace: "LEGACY_DIAGNOSTIC";
  production_eligible: false;
  mutations: MutationResult[];
}

function shellQuote(value: string): string {
  if (/^[A-Za-z0-9_./:@+=,-]+$/.test(value)) return value;
  return `'${value.replaceAll("'", "'\\''")}'`;
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
  if (run.private_prompt_commit) args.push("--private-prompt-commit", run.private_prompt_commit);
  if (run.prompt_repo_id) args.push("--prompt-repo-id", run.prompt_repo_id);
  if (run.prompt_sha256) args.push("--prompt-sha256", run.prompt_sha256);
  if (run.code_commit_hash) args.push("--code-commit-hash", run.code_commit_hash);
  return args.map(shellQuote).join(" ");
}

export async function runAutoresearchCycle(opts: AutoresearchCycleOptions): Promise<CycleResult> {
  const {
    cohort,
    maxMutations = 1,
    dryRun = false,
    forceAgent,
    fakeLlm = false,
    mutationMode = "auto",
    simulatedNow,
    promptsRoot,
    basePromptCommit,
    codeCommitHash,
    historicalSandbox = false,
    historicalRunId,
    deps,
    onLog,
  } = opts;
  const log = onLog ?? (() => undefined);
  const safeLog = (message: string) => log(redactSensitiveText(message));
  const results: MutationResult[] = [];

  if (simulatedNow && !historicalSandbox)
    throw new Error("simulatedNow requires historicalSandbox");
  if (
    historicalSandbox &&
    (!simulatedNow || !basePromptCommit || !codeCommitHash || !historicalRunId)
  ) {
    throw new Error(
      "historicalSandbox requires simulatedNow, historicalRunId, basePromptCommit, and codeCommitHash",
    );
  }
  if (historicalSandbox && mutationMode !== "prompt_rewrite") {
    throw new Error("historicalSandbox requires mutationMode=prompt_rewrite");
  }

  for (let index = 0; index < maxMutations; index += 1) {
    let triggerResult: Awaited<ReturnType<BridgeApi["autoresearchTrigger"]>>;
    try {
      triggerResult = await deps.api.autoresearchTrigger({
        cohort,
        ...(forceAgent ? { force_agent: forceAgent } : {}),
        ...(dryRun ? { dry_run: true } : {}),
        ...(historicalSandbox ? { historical_sandbox: true } : {}),
        ...(historicalRunId ? { historical_run_id: historicalRunId } : {}),
        ...(simulatedNow ? { as_of_date: simulatedNow } : {}),
        ...(basePromptCommit ? { base_prompt_commit: basePromptCommit } : {}),
        ...(codeCommitHash ? { code_commit_hash: codeCommitHash } : {}),
      });
    } catch (error) {
      safeLog(`trigger blocked: ${(error as Error).message}`);
      break;
    }

    safeLog(
      `triggered: agent=${triggerResult.agent} version_id=${triggerResult.version_id} branch=${triggerResult.branch_name}`,
    );
    if (
      historicalSandbox &&
      triggerResult.existing &&
      triggerResult.version_id !== null &&
      triggerResult.prompt_commit_hash
    ) {
      results.push({
        agent: triggerResult.agent,
        version_id: triggerResult.version_id,
        status: "needs_fill",
        branch_name: triggerResult.branch_name,
        prompt_commit_hash: triggerResult.prompt_commit_hash,
        ...(triggerResult.prompt_sha256 ? { prompt_sha256: triggerResult.prompt_sha256 } : {}),
        ...(triggerResult.prompt_base_commit_hash
          ? { prompt_base_commit_hash: triggerResult.prompt_base_commit_hash }
          : {}),
        summary: "recovered existing historical candidate",
      });
      continue;
    }

    let mutation: Awaited<ReturnType<typeof mutate>>;
    try {
      mutation = await mutate({
        cohort,
        agent: triggerResult.agent,
        deps: { llm: deps.llm, api: deps.api },
        ...(promptsRoot ? { promptsRoot } : {}),
        ...(fakeLlm ? { fakeLlm: true } : {}),
      });
    } catch (error) {
      results.push({
        agent: triggerResult.agent,
        version_id: triggerResult.version_id,
        status: "error",
        error: redactSensitiveText(`mutation failed: ${(error as Error).message}`),
      });
      continue;
    }
    safeLog(`mutated: ${mutation.modification_summary}`);

    if (dryRun) {
      results.push({
        agent: triggerResult.agent,
        version_id: triggerResult.version_id,
        status: "dry_run",
        summary: mutation.modification_summary,
      });
      continue;
    }

    const versionId = triggerResult.version_id;
    if (versionId === null) {
      results.push({
        agent: triggerResult.agent,
        version_id: null,
        status: "error",
        error: "trigger returned no version_id (non-dry-run)",
      });
      continue;
    }

    let writeResult: Awaited<ReturnType<BridgeApi["promptsWrite"]>>;
    try {
      writeResult = await deps.api.promptsWrite({
        agent: triggerResult.agent,
        cohort,
        contents: { zh: mutation.zh_prompt, en: mutation.en_prompt },
        target: "private_git",
        branch: triggerResult.branch_name,
        ...(basePromptCommit ? { base_ref: basePromptCommit } : {}),
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
        code_commit_hash: codeCommitHash ?? triggerResult.base_commit,
      });
    } catch (error) {
      results.push({
        agent: triggerResult.agent,
        version_id: versionId,
        status: "error",
        error: redactSensitiveText(`write failed: ${(error as Error).message}`),
      });
      continue;
    }

    let worktreePath: string | undefined;
    if (writeResult.target !== "private_git") {
      try {
        worktreePath = (
          await deps.api.autoresearchPrepareWorktree({ branch: triggerResult.branch_name })
        ).path;
      } catch (error) {
        safeLog(`worktree prep failed: ${(error as Error).message}`);
      }
    }

    let status: MutationResult["status"] = "needs_fill";
    let deltaSharpe: number | undefined;
    let fillCommands: string[] | undefined;
    let evalError: string | undefined;
    if (!historicalSandbox) {
      try {
        const evaluation = await deps.api.autoresearchEvaluatePending({
          cohort,
          version_id: versionId,
        });
        const row = evaluation.results.find((candidate) => candidate.version_id === versionId);
        if (row) {
          if (
            ["kept", "reverted", "eligible_for_promotion", "invalid", "legacy_unverified"].includes(
              row.status,
            )
          ) {
            status = row.status as MutationResult["status"];
            deltaSharpe = row.delta_sharpe;
          } else if (row.status === "incompatible") {
            status = "incompatible";
            evalError = redactSensitiveText(
              row.detail ?? "prompt is incompatible with current code",
            );
          } else if (row.status === "needs_fill") {
            fillCommands = (row.missing_runs ?? []).map(backtestFillCommand);
          } else if (row.status === "error") {
            status = "error";
            evalError = redactSensitiveText(row.detail ?? "evaluation failed");
          }
        }
      } catch (error) {
        status = "error";
        evalError = redactSensitiveText((error as Error).message || "unknown");
      }
    }

    if (worktreePath) {
      await deps.api.autoresearchCleanupWorktree({ path: worktreePath }).catch(() => undefined);
    }
    results.push({
      agent: triggerResult.agent,
      version_id: versionId,
      status,
      ...(deltaSharpe !== undefined ? { delta_sharpe: deltaSharpe } : {}),
      ...(evalError ? { error: evalError } : {}),
      ...(fillCommands?.length ? { fill_commands: fillCommands } : {}),
      summary: mutation.modification_summary,
      branch_name: triggerResult.branch_name,
      ...((writeResult.prompt_commit_hash ?? writeResult.commit_hash)
        ? { prompt_commit_hash: writeResult.prompt_commit_hash ?? writeResult.commit_hash }
        : {}),
      ...(writeResult.prompt_sha256 ? { prompt_sha256: writeResult.prompt_sha256 } : {}),
      ...(writeResult.prompt_base_commit_hash
        ? { prompt_base_commit_hash: writeResult.prompt_base_commit_hash }
        : {}),
    });
  }
  return {
    namespace: "LEGACY_DIAGNOSTIC",
    production_eligible: false,
    mutations: results,
  };
}
