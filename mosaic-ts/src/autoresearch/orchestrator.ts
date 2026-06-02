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
  /** Use the deterministic canned mutation (Plan §11.5 4F --fake-llm smoke). */
  fakeLlm?: boolean;
  deps: {
    llm: BaseChatModel;
    api: BridgeApi;
  };
  onLog?: (msg: string) => void;
}

export interface MutationResult {
  agent: string;
  version_id: number | null;
  status: "kept" | "reverted" | "dry_run" | "needs_fill" | "incompatible" | "error";
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

export async function runAutoresearchCycle(opts: AutoresearchCycleOptions): Promise<CycleResult> {
  const {
    cohort,
    // evalDays is reserved for future use when backtest-fill integration
    // allows specifying the evaluation window directly from the orchestrator.
    maxMutations = 1,
    dryRun = false,
    forceAgent,
    fakeLlm = false,
    deps,
    onLog,
  } = opts;

  const log = onLog ?? (() => {});
  const safeLog = (msg: string) => log(redactSensitiveText(msg));
  const results: MutationResult[] = [];

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

    // 2. Mutate: generate prompt rewrite via LLM
    let mutation: Awaited<ReturnType<typeof mutate>>;
    try {
      mutation = await mutate({
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

    // 3. Dry-run: record result without committing
    if (dryRun) {
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

    // 4. Write prompts on branch
    let writeResult: Awaited<ReturnType<BridgeApi["promptsWrite"]>>;
    try {
      writeResult = await deps.api.promptsWrite({
        agent: triggerResult.agent,
        cohort,
        contents: { zh: mutation.zh_prompt, en: mutation.en_prompt },
        target: "private_git",
        branch: triggerResult.branch_name,
        message: `autoresearch: ${mutation.modification_summary}`,
      });
    } catch (err) {
      results.push({
        agent: triggerResult.agent,
        version_id: versionId,
        status: "error",
        error: redactSensitiveText(`write failed: ${(err as Error).message}`),
      });
      continue;
    }

    // 5. Record mutation in store
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
        if (thisEval.status === "kept" || thisEval.status === "reverted") {
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
