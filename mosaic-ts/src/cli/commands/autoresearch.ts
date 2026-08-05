/**
 * Prompt Autoresearch CLI. Candidate generation and shadow experiments remain
 * separate from the existing Prompt Release activation authority.
 *
 * The active surface generates private Candidates, runs frozen shadow
 * experiments, and exposes read-only legacy diagnostics.
 */

import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import type { Command } from "commander";
import pc from "picocolors";
import { z } from "zod";
import { canonicalJsonHash } from "../../agents/helpers/canonical_json.js";
import {
  BridgePromptExperimentRepository,
  type PromptExperimentAgentExecutor,
  type PromptExperimentEvaluator,
} from "../../autoresearch/prompt_experiment_runner.js";
import {
  assertCandidateMatchesTrainingSnapshot,
  PromptCandidateSchema,
  PromptOptimizerTargetSchema,
} from "../../autoresearch/prompt_optimizer_contract.js";
import {
  PromptOptimizerShadowPlanSchema,
  runPromptOptimizerShadowPlan,
} from "../../autoresearch/prompt_optimizer_shadow_runner.js";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";
import { redactSensitiveText } from "../../security/redaction.js";
import { pad } from "../_format.js";

interface LogOptions {
  cohort?: string;
  days?: string;
}

interface BranchesOptions {
  cohort?: string;
}

export const PromptCandidateGenerationRequestSchema = z
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
    createdAt: z.iso.datetime({ offset: true }),
  })
  .strict();

export type PromptCandidateGenerationRequest = z.infer<
  typeof PromptCandidateGenerationRequestSchema
>;

export function buildPrivateCandidateRequest(
  request: PromptCandidateGenerationRequest,
  trainingProjection: unknown,
) {
  return {
    parentId: request.parentId,
    parentPromptCommit: request.parentPromptCommit,
    target: request.target,
    promptRefs: request.promptRefs,
    trainingProjection,
    createdAt: request.createdAt,
  };
}

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
    createdAt: request.createdAt,
  };
  const actual = {
    parentId: candidate.parentId,
    parentPromptCommit: candidate.parentPromptCommit,
    target: candidate.target,
    promptRefs: candidate.promptRefs,
    excludedSampleIdsHash: candidate.excludedSampleIdsHash,
    createdAt: candidate.createdAt,
  };
  if (canonicalJsonHash(actual) !== canonicalJsonHash(expected)) {
    throw new Error("private Prompt candidate request binding mismatch");
  }
}

export function runPrivateCandidateCli(privateCli: string, args: string[]): Promise<string> {
  return new Promise((resolveOutput, reject) => {
    execFile(process.execPath, [privateCli, ...args], { encoding: "utf8" }, (error, stdout) => {
      if (error) {
        reject(new Error("private Prompt candidate execution failed"));
      } else {
        resolveOutput(stdout.trim());
      }
    });
  });
}

export function registerAutoresearch(program: Command): void {
  const cmd = program
    .command("autoresearch")
    .description("Prompt Candidate generation, frozen experiments, and diagnostics.");

  cmd
    .command("generate-candidate")
    .description(
      "Build a training-only facet snapshot from sealed outcomes and invoke the private Prompt mutator.",
    )
    .requiredOption("--request <path>", "Public-safe Candidate request JSON")
    .requiredOption("--private-cli <path>", "Built private Prompt mutator CLI")
    .requiredOption("--private-repo <path>", "Private Prompt Git repository")
    .requiredOption(
      "--mutation-adapter <path>",
      "Tracked adapter inside --private-repo at that repository's exact HEAD",
    )
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
          const projection = await api.promptOptimizerTrainingProjection({
            agent_id: request.target.agentId,
            stage: request.target.stage,
            cohort: request.target.cohort,
            cutoff_at: request.cutoffAt,
            excluded_sample_ids: request.excludedSampleIds,
          });
          const privateRequestPath = resolve(temporaryRoot, "candidate-request.json");
          await writeFile(
            privateRequestPath,
            `${JSON.stringify(buildPrivateCandidateRequest(request, projection))}\n`,
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
          assertCandidateMatchesTrainingSnapshot(candidate, projection);
          if (
            typeof output.promptCommit !== "string" ||
            !/^[0-9a-f]{40}$/.test(output.promptCommit)
          ) {
            throw new Error("private Prompt candidate commit is invalid");
          }
          await api.promptOptimizerPutCandidate(candidate);
          console.log(
            `candidate=${candidate.candidateId} prompt_commit=${output.promptCommit} ` +
              `training_projection=${candidate.trainingProjectionHash}`,
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
        const adapterPath = resolve(opts.adapter);
        const adapterHash = `sha256:${createHash("sha256")
          .update(await readFile(adapterPath))
          .digest("hex")}`;
        if (
          plan.environment.executorAdapterHash !== adapterHash ||
          plan.environment.evaluatorAdapterHash !== adapterHash
        ) {
          throw new Error("shadow adapter content hash does not match the frozen plan");
        }
        const adapter = (await import(pathToFileURL(adapterPath).href)) as {
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
          authorizedPolicyHashes: new Set(
            (process.env.MOSAIC_PROMPT_PROMOTION_POLICY_HASHES ?? "")
              .split(",")
              .map((value) => value.trim())
              .filter(Boolean),
          ),
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
