/**
 * Prompt Autoresearch CLI. Candidate generation and shadow experiments remain
 * separate from the existing Prompt Release activation authority.
 *
 * Subcommands:
 *   - trigger: run the autoresearch mutation cycle
 *   - evaluate: evaluate pending mutations
 *   - log: view autoresearch event log
 *   - branches: list active feature branches
 *   - revert: manually revert a modification
 */

import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import type { Command } from "commander";
import pc from "picocolors";
import { z } from "zod";
import { canonicalJsonHash } from "../../agents/helpers/canonical_json.js";
import { runAutoresearchCycle } from "../../autoresearch/orchestrator.js";
import {
  BridgePromptExperimentRepository,
  type PromptExperimentAgentExecutor,
  type PromptExperimentEvaluator,
} from "../../autoresearch/prompt_experiment_runner.js";
import {
  PromptCandidateSchema,
  PromptOptimizerTargetSchema,
} from "../../autoresearch/prompt_optimizer_contract.js";
import {
  PromptOptimizerShadowPlanSchema,
  runPromptOptimizerShadowPlan,
} from "../../autoresearch/prompt_optimizer_shadow_runner.js";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";
import { createLlmFromConfig } from "../../llm/factory.js";
import { redactSensitiveText } from "../../security/redaction.js";
import { buildFakeLlmHandle } from "../_backtest_helpers.js";
import { pad } from "../_format.js";

interface TriggerOptions {
  cohort?: string;
  agent?: string;
  max?: string;
  dryRun?: boolean;
  fakeLlm?: boolean;
  mutationMode?: "auto" | "prompt_rewrite";
  evalDays?: string;
  llmProvider?: string;
  model?: string;
  baseUrl?: string;
}

interface EvaluateOptions {
  cohort?: string;
}

interface PromotionOptions {
  versionId: string;
  decision: "revert";
  approvedBy: string;
  approvalPolicy: "domain_release_manual_v1" | "decision_release_manual_v1";
  reason: string;
}

interface LogOptions {
  cohort?: string;
  days?: string;
}

interface BranchesOptions {
  cohort?: string;
}

interface RevertOptions {
  versionId: string;
}

const PromptCandidateGenerationRequestSchema = z
  .object({
    parentId: z.string().trim().min(1),
    parentPromptCommit: z.string().regex(/^[0-9a-f]{40}$/),
    target: PromptOptimizerTargetSchema,
    promptRefs: z.object({ zh: z.string().trim().min(1), en: z.string().trim().min(1) }).strict(),
    cutoffAt: z.iso.datetime({ offset: true }),
    excludedSampleIds: z
      .array(z.string().trim().min(1))
      .min(1)
      .refine(
        (values) => new Set(values).size === values.length,
        "excluded sample IDs must be unique",
      ),
    mutatorConfigHash: z.string().regex(/^sha256:[0-9a-f]{64}$/),
    mutatorCommit: z.string().regex(/^[0-9a-f]{40}$/),
    createdAt: z.iso.datetime({ offset: true }),
  })
  .strict();

type PromptCandidateGenerationRequest = z.infer<typeof PromptCandidateGenerationRequestSchema>;

export function assertPrivateCandidateMatchesRequest(
  candidate: z.infer<typeof PromptCandidateSchema>,
  request: PromptCandidateGenerationRequest,
): void {
  const expected = {
    parentId: request.parentId,
    parentPromptCommit: request.parentPromptCommit,
    target: request.target,
    promptRefs: request.promptRefs,
    excludedSampleIdsHash: canonicalJsonHash([...request.excludedSampleIds].sort()),
    mutatorConfigHash: request.mutatorConfigHash,
    mutatorCommit: request.mutatorCommit,
    createdAt: request.createdAt,
  };
  const actual = {
    parentId: candidate.parentId,
    parentPromptCommit: candidate.parentPromptCommit,
    target: candidate.target,
    promptRefs: candidate.promptRefs,
    excludedSampleIdsHash: candidate.excludedSampleIdsHash,
    mutatorConfigHash: candidate.mutatorConfigHash,
    mutatorCommit: candidate.mutatorCommit,
    createdAt: candidate.createdAt,
  };
  if (canonicalJsonHash(actual) !== canonicalJsonHash(expected)) {
    throw new Error("private Prompt candidate request binding mismatch");
  }
}

function runPrivateCandidateCli(privateCli: string, args: string[]): Promise<string> {
  return new Promise((resolveOutput, reject) => {
    execFile(
      process.execPath,
      [privateCli, ...args],
      { encoding: "utf8" },
      (error, stdout, stderr) => {
        if (error) {
          reject(new Error(`private Prompt candidate failed: ${stderr.trim() || error.message}`));
        } else {
          resolveOutput(stdout.trim());
        }
      },
    );
  });
}

export function registerAutoresearch(program: Command): void {
  const cmd = program
    .command("autoresearch")
    .description("Prompt Candidate generation, experiments, and legacy diagnostics.");

  cmd
    .command("generate-candidate")
    .description(
      "Build a training-only facet snapshot from sealed outcomes and invoke the private Prompt mutator.",
    )
    .requiredOption("--request <path>", "Public-safe Candidate request JSON")
    .requiredOption("--private-cli <path>", "Built private Prompt mutator CLI")
    .requiredOption("--private-repo <path>", "Private Prompt Git repository")
    .requiredOption("--mutation-adapter <path>", "Private mutation/alignment adapter module")
    .action(
      async (opts: {
        request: string;
        privateCli: string;
        privateRepo: string;
        mutationAdapter: string;
      }) => {
        const client = new BridgeClient();
        const temporaryRoot = await mkdtemp(resolve(tmpdir(), "mosaic-prompt-training-"));
        try {
          const request = PromptCandidateGenerationRequestSchema.parse(
            JSON.parse(await readFile(resolve(opts.request), "utf8")),
          );
          await client.start();
          const api = new BridgeApi(client);
          const history = await api.promptOptimizerTrainingHistory({
            agent_id: request.target.agentId,
            stage: request.target.stage,
            cohort: request.target.cohort,
            cutoff_at: request.cutoffAt,
            excluded_sample_ids: request.excludedSampleIds,
          });
          const privateRequestPath = resolve(temporaryRoot, "candidate-request.json");
          await writeFile(
            privateRequestPath,
            `${JSON.stringify({
              parentId: request.parentId,
              parentPromptCommit: request.parentPromptCommit,
              target: request.target,
              promptRefs: request.promptRefs,
              trainingHistory: history,
              mutatorConfigHash: request.mutatorConfigHash,
              mutatorCommit: request.mutatorCommit,
              createdAt: request.createdAt,
            })}\n`,
            { encoding: "utf8", mode: 0o600 },
          );
          const output = JSON.parse(
            await runPrivateCandidateCli(resolve(opts.privateCli), [
              "--request",
              privateRequestPath,
              "--adapter",
              resolve(opts.mutationAdapter),
              "--repo",
              resolve(opts.privateRepo),
            ]),
          ) as { candidate?: unknown; promptCommit?: unknown };
          const candidate = PromptCandidateSchema.parse(output.candidate);
          assertPrivateCandidateMatchesRequest(candidate, request);
          if (
            typeof output.promptCommit !== "string" ||
            !/^[0-9a-f]{40}$/.test(output.promptCommit)
          ) {
            throw new Error("private Prompt candidate commit is invalid");
          }
          await api.promptOptimizerPutCandidate(candidate);
          console.log(
            `candidate=${candidate.candidateId} prompt_commit=${output.promptCommit} ` +
              `training_snapshot=${candidate.trainingSnapshotId}`,
          );
        } catch (error) {
          console.error(`error: ${redactSensitiveText((error as Error).message)}`);
          process.exitCode = 1;
        } finally {
          await client.close();
          await rm(temporaryRoot, { recursive: true, force: true });
        }
      },
    );

  cmd
    .command("shadow-run")
    .description(
      "Run a preregistered Prompt Candidate family through validation and one-time holdout.",
    )
    .requiredOption(
      "--plan <path>",
      "Local uncommitted shadow-plan JSON; it may contain private policy values",
    )
    .requiredOption("--adapter <path>", "Local module exporting executor and evaluator adapters")
    .action(async (opts: { plan: string; adapter: string }) => {
      const client = new BridgeClient();
      try {
        const plan = PromptOptimizerShadowPlanSchema.parse(
          JSON.parse(await readFile(resolve(opts.plan), "utf8")),
        );
        const adapter = (await import(pathToFileURL(resolve(opts.adapter)).href)) as {
          executor?: PromptExperimentAgentExecutor;
          evaluator?: PromptExperimentEvaluator;
        };
        if (!adapter.executor?.execute || !adapter.evaluator?.evaluate) {
          throw new Error("shadow adapter must export executor.execute and evaluator.evaluate");
        }
        await client.start();
        const result = await runPromptOptimizerShadowPlan({
          plan,
          repository: new BridgePromptExperimentRepository(new BridgeApi(client)),
          executor: adapter.executor,
          evaluator: adapter.evaluator,
        });
        console.log(
          `shadow decision=${result.decision.decision} candidate=${result.decision.candidateId} ` +
            `experiment=${result.experiment.experimentId}`,
        );
      } catch (error) {
        console.error(`error: ${redactSensitiveText((error as Error).message)}`);
        process.exitCode = 1;
      } finally {
        await client.close();
      }
    });

  // ── autoresearch trigger ──────────────────────────────────────────────

  cmd
    .command("trigger")
    .description("Generate a legacy research candidate; it cannot promote a v2 prompt.")
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .option("--agent <name>", "Force a specific agent (skip constraint selection)")
    .option("--max <n>", "Max mutations per cycle (default 1)")
    .option("--dry-run", "Generate mutation but do not commit")
    .option("--fake-llm", "Use in-memory mock LLM (zero cost)")
    .option("--mutation-mode <mode>", "auto | prompt_rewrite")
    .option("--eval-days <n>", "Evaluation window in trading days (default 60)")
    .option("--llm-provider <name>", "Override LLM provider")
    .option("--model <name>", "Override LLM model")
    .option("--base-url <url>", "Override LLM base URL")
    .action(async (opts: TriggerOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      const cohort = opts.cohort ?? "cohort_default";

      try {
        await client.start();
        const config = await api.configGet();

        const llmHandle = opts.fakeLlm
          ? buildFakeLlmHandle()
          : createLlmFromConfig(config, {
              tier: "deep",
              ...(opts.llmProvider ? { provider: opts.llmProvider } : {}),
              ...(opts.model ? { model: opts.model } : {}),
              ...(opts.baseUrl ? { baseUrl: opts.baseUrl } : {}),
            });

        const maxMutations = opts.max ? Number.parseInt(opts.max, 10) : 1;
        const evalDays = opts.evalDays ? Number.parseInt(opts.evalDays, 10) : 60;

        console.log(
          pc.bold(
            `\nautoresearch trigger -- cohort=${cohort} max=${maxMutations}` +
              `${opts.dryRun ? " [DRY RUN]" : ""}`,
          ),
        );

        const result = await runAutoresearchCycle({
          cohort,
          evalDays,
          maxMutations,
          dryRun: opts.dryRun ?? false,
          ...(opts.agent ? { forceAgent: opts.agent } : {}),
          ...(opts.fakeLlm ? { fakeLlm: true } : {}),
          ...(opts.mutationMode ? { mutationMode: opts.mutationMode } : {}),
          deps: { llm: llmHandle.llm, api },
          onLog: (msg) => console.log(pc.dim(`  ${msg}`)),
        });

        // Print results
        console.log(pc.cyan(`\n=== Results (${result.mutations.length} mutations) ===`));
        for (const m of result.mutations) {
          const statusColor =
            m.status === "kept"
              ? pc.green
              : m.status === "reverted"
                ? pc.red
                : m.status === "error"
                  ? pc.red
                  : pc.yellow;
          console.log(
            `  ${pad(m.agent, 20)} ${statusColor(pad(m.status, 12))} ` +
              `${m.version_id != null ? `v${m.version_id}` : "(dry-run)"}` +
              (m.delta_sharpe != null ? ` delta=${m.delta_sharpe.toFixed(4)}` : "") +
              (m.summary ? ` -- ${m.summary}` : "") +
              (m.error ? ` [${m.error}]` : ""),
          );
        }
      } catch (err) {
        handleError(err, client);
      } finally {
        await client.close();
      }
    });

  // ── autoresearch evaluate ─────────────────────────────────────────────

  cmd
    .command("evaluate")
    .description("Evaluate pending legacy candidates for audit; never keep or promote.")
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .action(async (opts: EvaluateOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      const cohort = opts.cohort ?? "cohort_default";

      try {
        await client.start();
        console.log(pc.bold(`\nautoresearch evaluate -- cohort=${cohort}`));

        const { results } = await api.autoresearchEvaluatePending({ cohort });

        if (results.length === 0) {
          console.log(pc.dim("  no pending mutations to evaluate"));
        } else {
          console.log(pc.cyan(`\n  ${pad("version_id", 12)} ${pad("status", 12)} delta_sharpe`));
          console.log(pc.dim(`  ${"─".repeat(44)}`));
          for (const r of results) {
            const statusColor =
              r.status === "kept" ? pc.green : r.status === "reverted" ? pc.red : pc.yellow;
            console.log(
              `  ${pad(String(r.version_id), 12)} ${statusColor(pad(r.status, 12))} ` +
                (r.delta_sharpe != null ? r.delta_sharpe.toFixed(4) : "n/a"),
            );
          }
        }
      } catch (err) {
        handleError(err, client);
      } finally {
        await client.close();
      }
    });

  // ── autoresearch domain promotion review ──────────────────────────────

  cmd
    .command("review-domain")
    .description("Reject a legacy diagnostic mutation; it cannot enter Prompt Release.")
    .requiredOption("--version-id <id>", "Prompt version id")
    .requiredOption("--decision <decision>", "revert")
    .requiredOption("--approved-by <operator>", "Operator identity, prefixed with operator:")
    .requiredOption(
      "--approval-policy <policy>",
      "domain_release_manual_v1 | decision_release_manual_v1",
    )
    .requiredOption("--reason <text>", "Review rationale")
    .action(async (opts: PromotionOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        await client.start();
        if (opts.decision !== "revert") {
          throw new Error("--decision must be revert; this legacy path cannot promote");
        }
        if (
          !(["domain_release_manual_v1", "decision_release_manual_v1"] as const).includes(
            opts.approvalPolicy,
          )
        ) {
          throw new Error("--approval-policy is unsupported");
        }
        const result = await api.autoresearchReviewDomainPromotion({
          version_id: Number.parseInt(opts.versionId, 10),
          decision: "revert",
          approved_by: opts.approvedBy,
          approval_policy_id: opts.approvalPolicy,
          review_reason: opts.reason,
        });
        console.log(
          `${result.status} version=${result.version_id} decision=${result.decision_hash}`,
        );
      } catch (err) {
        handleError(err, client);
      } finally {
        await client.close();
      }
    });

  // ── autoresearch log ──────────────────────────────────────────────────

  cmd
    .command("log")
    .description("View autoresearch event log.")
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .option("--days <n>", "Show entries from the last N days (default 7)")
    .action(async (opts: LogOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      const cohort = opts.cohort ?? "cohort_default";
      const days = opts.days ? Number.parseInt(opts.days, 10) : 7;

      try {
        await client.start();
        console.log(pc.bold(`\nautoresearch log -- cohort=${cohort} days=${days}`));

        const { entries } = await api.autoresearchGetLog({ cohort, days });

        if (entries.length === 0) {
          console.log(pc.dim("  no log entries"));
        } else {
          console.log(
            pc.cyan(`\n  ${pad("time", 20)} ${pad("event", 12)} ${pad("agent", 16)} detail`),
          );
          console.log(pc.dim(`  ${"─".repeat(70)}`));
          for (const e of entries) {
            const time = e.created_at.slice(0, 19).replace("T", " ");
            console.log(
              `  ${pad(time, 20)} ${pad(e.event, 12)} ${pad(e.agent ?? "-", 16)} ${e.detail ?? ""}`,
            );
          }
        }
      } catch (err) {
        handleError(err, client);
      } finally {
        await client.close();
      }
    });

  // ── autoresearch branches ─────────────────────────────────────────────

  cmd
    .command("branches")
    .description("List active autoresearch feature branches.")
    .option("--cohort <name>", "Cohort id (default cohort_default)")
    .action(async (opts: BranchesOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      const cohort = opts.cohort ?? "cohort_default";

      try {
        await client.start();
        console.log(pc.bold(`\nautoresearch branches -- cohort=${cohort}`));

        const { branches } = await api.autoresearchListActiveBranches({ cohort });

        if (branches.length === 0) {
          console.log(pc.dim("  no active branches"));
        } else {
          console.log(
            pc.cyan(`\n  ${pad("id", 6)} ${pad("agent", 16)} ${pad("branch", 36)} created`),
          );
          console.log(pc.dim(`  ${"─".repeat(74)}`));
          for (const b of branches) {
            const time = b.created_at.slice(0, 19).replace("T", " ");
            console.log(
              `  ${pad(String(b.id), 6)} ${pad(b.agent, 16)} ${pad(b.branch_name, 36)} ${time}`,
            );
          }
        }
      } catch (err) {
        handleError(err, client);
      } finally {
        await client.close();
      }
    });

  // ── autoresearch revert ───────────────────────────────────────────────

  cmd
    .command("revert")
    .description("Manually revert a specific modification by version ID.")
    .requiredOption("--version-id <id>", "Version ID to revert")
    .action(async (opts: RevertOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      const versionId = Number.parseInt(opts.versionId, 10);

      try {
        await client.start();
        console.log(pc.bold(`\nautoresearch revert -- version_id=${versionId}`));

        const result = await api.autoresearchRevertModification({ version_id: versionId });

        if (result.ok) {
          console.log(pc.green(`  version ${versionId} reverted successfully`));
        } else {
          console.log(pc.yellow(`  revert returned ok=false for version ${versionId}`));
        }
      } catch (err) {
        handleError(err, client);
      } finally {
        await client.close();
      }
    });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function handleError(err: unknown, client: BridgeClient): void {
  if (err instanceof RpcError) {
    console.error(pc.red(`bridge error [${err.code}]: ${redactSensitiveText(err.message)}`));
  } else {
    console.error(pc.red(`error: ${redactSensitiveText((err as Error).message)}`));
  }
  const tail = client.stderrTail.trim();
  if (tail) {
    console.error(pc.dim("\n--- bridge stderr (tail) ---"));
    console.error(pc.dim(redactSensitiveText(tail).slice(-2000)));
  }
  process.exitCode = 1;
}

// pad() imported from ../_format.js (§14 R-T2: shared CJK + ANSI-aware).
