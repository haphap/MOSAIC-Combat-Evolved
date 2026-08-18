/**
 * Prompt Autoresearch CLI. Candidate generation and shadow experiments remain
 * separate from the existing Prompt Release activation authority.
 *
 * The active surface generates private Candidates, runs frozen shadow
 * experiments, and exposes read-only legacy diagnostics.
 */

import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { isAbsolute, relative, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";
import type { Command } from "commander";
import pc from "picocolors";
import { z } from "zod";
import { canonicalJsonHash } from "../../agents/helpers/canonical_json.js";
import {
  KnotGateDCandidateV1Schema,
  KnotGateDReceiptV1Schema,
} from "../../agents/prompts/prompt_release_contract.js";
import {
  CapabilityFullBundleV1Schema,
  loadCurrentCapabilityBindings,
  loadCurrentKnotGateDReleaseAuthority,
  type PromptTrainingProjectionV2,
  PromptTrainingProjectionV2Schema,
} from "../../autoresearch/capability_preservation_contract.js";
import { assertCurrentKnotTransitionAction } from "../../autoresearch/knot_gate_d_release_authority.js";
import {
  BridgePromptExperimentRepository,
  type PromptExperimentAgentExecutor,
  type PromptExperimentEvaluator,
} from "../../autoresearch/prompt_experiment_runner.js";
import {
  assertCandidateMatchesTrainingSnapshot,
  buildPromptCandidatePublication,
  PromptCandidateSchema,
  PromptOptimizerTargetSchema,
  PromptSourceIdSchema,
} from "../../autoresearch/prompt_optimizer_contract.js";
import {
  PromptOptimizerShadowPlanSchema,
  runPromptOptimizerShadowPlan,
} from "../../autoresearch/prompt_optimizer_shadow_runner.js";
import { BridgeApi, BridgeClient, findRepoRoot, RpcError } from "../../bridge/index.js";
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
    promptSourceId: PromptSourceIdSchema,
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

const Sha256Schema = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const CommitSchema = z.string().regex(/^[0-9a-f]{40}$/);

export const GateDProjectionBuildRequestSchema = z
  .object({
    agent_id: z.string().trim().min(1),
    stage: z.string().trim().min(1),
    cohort: z.string().trim().min(1),
    cutoff_at: z.iso.datetime({ offset: true }),
    excluded_sample_ids: z.array(z.string().trim().min(1)).default([]),
  })
  .strict();

export const GateDCandidateBuildRequestSchema = z
  .object({
    capability_full_bundle: CapabilityFullBundleV1Schema,
    experiment_ids_by_stage: z.record(z.string().min(1), z.string().trim().min(1)),
    training_projection_hashes_by_stage: z.record(z.string().min(1), Sha256Schema),
    public_private_pin: z
      .object({
        public_commit: CommitSchema,
        public_tree_hash: Sha256Schema,
        private_commit: CommitSchema,
        private_tree_hash: Sha256Schema,
        private_companion_pin_hash: Sha256Schema,
      })
      .strict(),
  })
  .strict();

const GateDPiReviewSchema = z
  .object({
    repository: z.enum(["public", "private"]),
    reviewed_commit: CommitSchema,
    review_ref: z.string().trim().min(1),
    disposition: z.literal("APPROVE"),
    reviewed_candidate_hash: Sha256Schema,
  })
  .strict();

export const GateDReceiptBuildRequestSchema = z
  .object({
    candidate: KnotGateDCandidateV1Schema,
    public_pi_review: GateDPiReviewSchema,
    private_pi_review: GateDPiReviewSchema,
  })
  .strict();

type CapabilityUseAggregate = PromptTrainingProjectionV2["capabilityUseAggregates"][number];

export interface CapabilityUseContext {
  schemaVersion: "prompt_candidate_capability_use_context_v1";
  sourceProjectionHash: string;
  target: PromptCandidateGenerationRequest["target"];
  capabilityUseAggregates: CapabilityUseAggregate[];
  contextHash: string;
}

function buildCapabilityUseContext(
  request: PromptCandidateGenerationRequest,
  trainingProjectionV2: PromptTrainingProjectionV2,
): CapabilityUseContext {
  if (canonicalJsonHash(trainingProjectionV2.target) !== canonicalJsonHash(request.target)) {
    throw new Error("private Prompt v2 target mismatch");
  }
  const targetBindingIds = loadCurrentCapabilityBindings()
    .filter(
      (binding) =>
        binding.activation_state === "active" && binding.agent_id === request.target.agentId,
    )
    .map((binding) => binding.binding_id)
    .sort();
  if (targetBindingIds.length === 0) {
    throw new Error("private Prompt target has no active capability bindings");
  }
  const rows = trainingProjectionV2.capabilityUseAggregates.filter((row) =>
    targetBindingIds.includes(row.binding_id),
  );
  const actualIds = rows.map((row) => row.binding_id).sort();
  if (
    actualIds.length !== targetBindingIds.length ||
    JSON.stringify(actualIds) !== JSON.stringify(targetBindingIds)
  ) {
    throw new Error("private Prompt capability aggregate closure mismatch");
  }
  const body = {
    schemaVersion: "prompt_candidate_capability_use_context_v1" as const,
    sourceProjectionHash: trainingProjectionV2.projectionHash,
    target: request.target,
    capabilityUseAggregates: rows.sort((left, right) =>
      left.binding_id.localeCompare(right.binding_id),
    ),
  };
  return { ...body, contextHash: canonicalJsonHash(body) };
}

export function buildPrivateCandidateRequest(
  request: PromptCandidateGenerationRequest,
  trainingProjection: unknown,
  trainingProjectionV2: PromptTrainingProjectionV2,
) {
  return {
    parentId: request.parentId,
    parentPromptCommit: request.parentPromptCommit,
    target: request.target,
    promptRefs: request.promptRefs,
    trainingProjection,
    capabilityUseContext: buildCapabilityUseContext(request, trainingProjectionV2),
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

export function buildPrivateCandidateCliArgs(input: {
  requestPath: string;
  mutationAdapter: string;
  privateRepo: string;
  publicationRemote: string;
}): string[] {
  return [
    "--request",
    input.requestPath,
    "--adapter",
    resolve(input.mutationAdapter),
    "--repo",
    resolve(input.privateRepo),
    "--publication-remote",
    input.publicationRemote,
  ];
}

function runGit(repo: string, args: ReadonlyArray<string>): Promise<string> {
  return new Promise((resolveOutput, reject) => {
    execFile(
      "git",
      ["-C", repo, ...args],
      { encoding: "utf8", maxBuffer: 8 * 1024 * 1024 },
      (error, stdout) => {
        if (error) {
          reject(new Error(`shadow public checkout Git command failed: ${args[0]}`));
        } else {
          resolveOutput(stdout.trim());
        }
      },
    );
  });
}

function adapterEntryPath(repo: string, adapter: string, kind: "executor" | "evaluator"): string {
  const entryPath = relative(repo, adapter);
  if (
    entryPath === "" ||
    entryPath === ".." ||
    entryPath.startsWith(`..${sep}`) ||
    isAbsolute(entryPath)
  ) {
    throw new Error(`shadow ${kind} adapter must be inside the frozen public checkout`);
  }
  return entryPath.split(sep).join("/");
}

async function resolveFrozenAdapterPath(input: {
  repoPath: string;
  repoRealPath: string;
  codeCommit: string;
  adapter: string;
  kind: "executor" | "evaluator";
}): Promise<string> {
  const adapterPath = resolve(input.adapter);
  const entryPath = adapterEntryPath(input.repoPath, adapterPath, input.kind);
  const adapterRealPath = await realpath(adapterPath);
  adapterEntryPath(input.repoRealPath, adapterRealPath, input.kind);
  await runGit(input.repoRealPath, ["cat-file", "-e", `${input.codeCommit}:${entryPath}`]).catch(
    () => {
      throw new Error(
        `shadow ${input.kind} adapter must be tracked by the frozen public checkout commit`,
      );
    },
  );
  return adapterRealPath;
}

export async function loadFrozenShadowAdapters(input: {
  publicRepo: string;
  executorAdapter: string;
  evaluatorAdapter: string;
  environment: {
    codeCommit: string;
    executorAdapterHash: string;
    evaluatorAdapterHash: string;
  };
}): Promise<{
  executor: PromptExperimentAgentExecutor;
  evaluator: PromptExperimentEvaluator;
}> {
  const repoPath = resolve(input.publicRepo);
  const repoRealPath = await realpath(repoPath);
  const head = await runGit(repoRealPath, ["rev-parse", "--verify", "HEAD^{commit}"]);
  if (head !== input.environment.codeCommit) {
    throw new Error("shadow public checkout does not match the frozen code commit");
  }
  if (await runGit(repoRealPath, ["status", "--porcelain=v1", "--untracked-files=all"])) {
    throw new Error("shadow public checkout must be clean, including untracked files");
  }
  const [executorPath, evaluatorPath] = await Promise.all([
    resolveFrozenAdapterPath({
      repoPath,
      repoRealPath,
      codeCommit: input.environment.codeCommit,
      adapter: input.executorAdapter,
      kind: "executor",
    }),
    resolveFrozenAdapterPath({
      repoPath,
      repoRealPath,
      codeCommit: input.environment.codeCommit,
      adapter: input.evaluatorAdapter,
      kind: "evaluator",
    }),
  ]);
  if (executorPath === evaluatorPath) {
    throw new Error("shadow executor and evaluator adapters must be separate modules");
  }
  const [executorBytes, evaluatorBytes] = await Promise.all([
    readFile(executorPath),
    readFile(evaluatorPath),
  ]);
  const executorHash = `sha256:${createHash("sha256").update(executorBytes).digest("hex")}`;
  const evaluatorHash = `sha256:${createHash("sha256").update(evaluatorBytes).digest("hex")}`;
  if (input.environment.executorAdapterHash !== executorHash) {
    throw new Error("shadow executor adapter content hash does not match the frozen plan");
  }
  if (input.environment.evaluatorAdapterHash !== evaluatorHash) {
    throw new Error("shadow evaluator adapter content hash does not match the frozen plan");
  }
  const [executorModule, evaluatorModule] = (await Promise.all([
    import(pathToFileURL(executorPath).href),
    import(pathToFileURL(evaluatorPath).href),
  ])) as [{ executor?: PromptExperimentAgentExecutor }, { evaluator?: PromptExperimentEvaluator }];
  if (!executorModule.executor?.execute) {
    throw new Error("shadow executor adapter must export executor.execute");
  }
  if (!evaluatorModule.evaluator?.evaluate) {
    throw new Error("shadow evaluator adapter must export evaluator.evaluate");
  }
  return { executor: executorModule.executor, evaluator: evaluatorModule.evaluator };
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
      "--publication-remote <name>",
      "Private Git remote used to durably publish the Candidate commit",
    )
    .requiredOption(
      "--mutation-adapter <path>",
      "Tracked adapter inside --private-repo at that repository's exact HEAD",
    )
    .action(
      async (opts: {
        request: string;
        privateCli: string;
        privateRepo: string;
        publicationRemote: string;
        mutationAdapter: string;
      }) => {
        await assertCurrentKnotTransitionAction(
          "GENERATE_CANDIDATE",
          process.env.MOSAIC_ACTIVE_PROMPT_RELEASE_REGISTRY_ROOT?.trim() ?? "",
        );
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
          const projectionV2 = await api.promptOptimizerTrainingProjectionV2({
            agent_id: request.target.agentId,
            stage: request.target.stage,
            cohort: request.target.cohort,
            cutoff_at: request.cutoffAt,
            excluded_sample_ids: request.excludedSampleIds,
          });
          const privateRequestPath = resolve(temporaryRoot, "candidate-request.json");
          await writeFile(
            privateRequestPath,
            `${JSON.stringify(buildPrivateCandidateRequest(request, projection, projectionV2))}\n`,
            { encoding: "utf8", mode: 0o600 },
          );
          const output = JSON.parse(
            await runPrivateCandidateCli(
              resolve(opts.privateCli),
              buildPrivateCandidateCliArgs({
                requestPath: privateRequestPath,
                mutationAdapter: opts.mutationAdapter,
                privateRepo: opts.privateRepo,
                publicationRemote: opts.publicationRemote,
              }),
            ),
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
          const publication = buildPromptCandidatePublication({
            candidate,
            promptSourceId: request.promptSourceId,
            candidatePromptCommit: output.promptCommit,
          });
          await api.promptOptimizerPutTrainingProjection(projection);
          await api.promptOptimizerPutTrainingProjectionV2(projectionV2);
          await api.promptOptimizerPutCandidate(candidate);
          await api.promptOptimizerPutCandidatePublication(publication);
          console.log(
            `candidate=${candidate.candidateId} prompt_commit=${output.promptCommit} ` +
              `publication=${publication.publicationHash} ` +
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
    .requiredOption("--executor-adapter <path>", "Local module exporting executor.execute")
    .requiredOption("--evaluator-adapter <path>", "Separate module exporting evaluator.evaluate")
    .action(async (opts: { plan: string; executorAdapter: string; evaluatorAdapter: string }) => {
      await assertCurrentKnotTransitionAction(
        "RUN_EXPERIMENT",
        process.env.MOSAIC_ACTIVE_PROMPT_RELEASE_REGISTRY_ROOT?.trim() ?? "",
      );
      const client = new BridgeClient();
      try {
        const plan = PromptOptimizerShadowPlanSchema.parse(
          JSON.parse(await readFile(resolve(opts.plan), "utf8")),
        );
        const adapters = await loadFrozenShadowAdapters({
          publicRepo: findRepoRoot(),
          executorAdapter: opts.executorAdapter,
          evaluatorAdapter: opts.evaluatorAdapter,
          environment: plan.environment,
        });
        await client.start();
        const result = await runPromptOptimizerShadowPlan({
          plan,
          repository: new BridgePromptExperimentRepository(new BridgeApi(client)),
          executor: adapters.executor,
          evaluator: adapters.evaluator,
          authorizedPolicyHashes: new Set(
            (process.env.MOSAIC_PROMPT_PROMOTION_POLICY_HASHES ?? "")
              .split(",")
              .map((value) => value.trim())
              .filter(Boolean),
          ),
          fixedPointAuthority: loadCurrentKnotGateDReleaseAuthority(),
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

  cmd
    .command("build-gate-d-projection")
    .description("Build and persist one current-track KNOT Gate-D training projection v2.")
    .requiredOption("--request <path>", "Public-safe projection request JSON")
    .requiredOption("--out <path>", "Output projection JSON")
    .action(async (opts: { request: string; out: string }) => {
      const client = new BridgeClient();
      try {
        const request = GateDProjectionBuildRequestSchema.parse(
          JSON.parse(await readFile(resolve(opts.request), "utf8")),
        );
        await client.start();
        const api = new BridgeApi(client);
        const projection = PromptTrainingProjectionV2Schema.parse(
          await api.promptOptimizerTrainingProjectionV2(request),
        );
        await api.promptOptimizerPutTrainingProjectionV2(projection);
        await writeFile(resolve(opts.out), `${JSON.stringify(projection, null, 2)}\n`, "utf8");
        console.log(`projection=${projection.projectionHash}`);
      } catch (error) {
        console.error(`error: ${redactSensitiveText((error as Error).message)}`);
        process.exitCode = 1;
      } finally {
        await client.close();
      }
    });

  cmd
    .command("build-gate-d-candidate")
    .description("Build the exact 28-stage/183-binding public Gate-D candidate.")
    .requiredOption("--request <path>", "Public-safe Gate-D candidate request JSON")
    .requiredOption("--out <path>", "Output candidate JSON")
    .action(async (opts: { request: string; out: string }) => {
      const client = new BridgeClient();
      try {
        const request = GateDCandidateBuildRequestSchema.parse(
          JSON.parse(await readFile(resolve(opts.request), "utf8")),
        );
        await client.start();
        const candidate = await new BridgeApi(client).promptOptimizerBuildKnotGateDCandidate(
          request,
        );
        await writeFile(resolve(opts.out), `${JSON.stringify(candidate, null, 2)}\n`, "utf8");
        console.log(`gate_d_candidate=${candidate.candidate_hash}`);
      } catch (error) {
        console.error(`error: ${redactSensitiveText((error as Error).message)}`);
        process.exitCode = 1;
      } finally {
        await client.close();
      }
    });

  cmd
    .command("build-gate-d-receipt")
    .description("Bind approved public/private Pi reviews into a Gate-D receipt.")
    .requiredOption("--request <path>", "Reviewed Gate-D receipt request JSON")
    .requiredOption("--out <path>", "Output receipt JSON")
    .action(async (opts: { request: string; out: string }) => {
      const client = new BridgeClient();
      try {
        const request = GateDReceiptBuildRequestSchema.parse(
          JSON.parse(await readFile(resolve(opts.request), "utf8")),
        );
        await client.start();
        const receipt = KnotGateDReceiptV1Schema.parse(
          await new BridgeApi(client).promptOptimizerBuildKnotGateDReceipt(request),
        );
        await writeFile(resolve(opts.out), `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
        console.log(`gate_d_receipt=${receipt.receipt_hash}`);
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
