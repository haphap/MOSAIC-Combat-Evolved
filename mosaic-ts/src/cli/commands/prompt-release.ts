import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import type { Command } from "commander";
import { z } from "zod";
import { canonicalJsonHash } from "../../agents/helpers/canonical_json.js";
import {
  type ActivePromptReleaseManifest,
  ActivePromptReleaseManifestSchema,
} from "../../agents/prompts/prompt_release_contract.js";
import {
  assertCurrentKnotTransitionAction,
  assertKnotGateDBootstrapReleaseTransition,
  buildKnotGateDBootstrapManifest,
  stageKnotGateDBootstrapRelease,
} from "../../autoresearch/knot_gate_d_release_authority.js";
import { authorizeStoredPromptPromotion } from "../../autoresearch/prompt_promotion_authority.js";
import { PromptPromotionPolicySchema } from "../../autoresearch/prompt_promotion_policy.js";
import {
  buildPromptReleaseCanarySloArtifact,
  PromptReleaseCanaryEventJournal,
  type PromptReleaseCanarySloArtifact,
  PromptReleaseCanarySloArtifactSchema,
} from "../../autoresearch/prompt_release_canary_slo.js";
import {
  activatePromptRelease,
  buildPromptReleaseBaselineManifest,
  PromptReleaseBaselineApprovalRecordSchema,
  provisionPromptReleaseBaseline,
  rollbackPromptRelease,
  stagePromptRelease,
  startPromptReleaseCanary,
} from "../../autoresearch/prompt_release_manager.js";
import { ActivePromptReleaseRegistry } from "../../autoresearch/release_registry.js";
import { BridgeApi, BridgeClient } from "../../bridge/index.js";
import { redactSensitiveText } from "../../security/redaction.js";

interface CommonOptions {
  registryRoot?: string;
}

function required(value: string | undefined, envName: string, optionName: string): string {
  const resolved = value?.trim() || process.env[envName]?.trim();
  if (!resolved) throw new Error(`${optionName} or ${envName} is required`);
  return resolved;
}

function registryRoot(opts: CommonOptions): string {
  return required(
    opts.registryRoot,
    "MOSAIC_ACTIVE_PROMPT_RELEASE_REGISTRY_ROOT",
    "--registry-root",
  );
}

function optionalRegistryRoot(opts: CommonOptions): string {
  return (
    opts.registryRoot?.trim() ||
    process.env.MOSAIC_ACTIVE_PROMPT_RELEASE_REGISTRY_ROOT?.trim() ||
    ""
  );
}

async function assertTransitionOrGateDBootstrap(
  action: "START_PROMPT_CANARY" | "ACTIVATE_PROMPT_RELEASE",
  root: string,
  releaseId: string,
): Promise<void> {
  try {
    await assertCurrentKnotTransitionAction(action, root);
  } catch {
    await assertKnotGateDBootstrapReleaseTransition(action, root, releaseId);
  }
}

function parseMode(value: string): "paper" | "backtest" | "live" {
  if (value === "paper" || value === "backtest" || value === "live") return value;
  throw new Error("--account-mode must be paper, backtest, or live");
}

function parsePolicy(value: string): "domain_release_manual_v1" | "decision_release_manual_v1" {
  if (value === "domain_release_manual_v1" || value === "decision_release_manual_v1") {
    return value;
  }
  throw new Error("--approval-policy is unsupported");
}

async function parseSloArtifact(path: string): Promise<PromptReleaseCanarySloArtifact> {
  return PromptReleaseCanarySloArtifactSchema.parse(JSON.parse(await readFile(path, "utf-8")));
}

function reportError(error: unknown): void {
  console.error(`error: ${redactSensitiveText((error as Error).message)}`);
  process.exitCode = 1;
}

export function registerPromptRelease(program: Command): void {
  const command = program
    .command("prompt-release")
    .description("Manage staged, canary, active, and rolled-back prompt releases.");

  command
    .command("stage")
    .requiredOption("--candidate-id <id>", "Eligible Prompt Candidate id")
    .requiredOption("--experiment-id <id>", "Completed Prompt experiment id")
    .requiredOption("--promotion-policy <path>", "Installed promotion policy JSON")
    .requiredOption("--private-prompt-commit <hash>", "Private Prompt Git commit")
    .requiredOption("--code-commit <hash>", "Public code Git commit")
    .requiredOption(
      "--execution-behavior-release-ref <path>",
      "Immutable execution behavior archive ref at the public code commit",
    )
    .requiredOption("--release-id <id>", "Immutable release id")
    .option("--registry-root <path>", "Release registry root")
    .option("--private-prompts-repo <path>", "Private prompt repository")
    .option("--cohort <name>", "Release cohort", "cohort_default")
    .option("--account-mode <mode>", "paper | backtest | live", "paper")
    .option(
      "--approval-policy <id>",
      "domain_release_manual_v1 | decision_release_manual_v1",
      "decision_release_manual_v1",
    )
    .action(
      async (opts: {
        candidateId: string;
        experimentId: string;
        promotionPolicy: string;
        privatePromptCommit: string;
        codeCommit: string;
        executionBehaviorReleaseRef: string;
        releaseId: string;
        registryRoot?: string;
        privatePromptsRepo?: string;
        cohort: string;
        accountMode: string;
        approvalPolicy: string;
      }) => {
        await assertCurrentKnotTransitionAction("STAGE_PROMPT_RELEASE", optionalRegistryRoot(opts));
        const client = new BridgeClient();
        const api = new BridgeApi(client);
        try {
          await client.start();
          const candidate = await api.promptOptimizerGetCandidate(opts.candidateId);
          if (!candidate) throw new Error(`Prompt Candidate not found: ${opts.candidateId}`);
          const candidatePublication = await api.promptOptimizerGetCandidatePublication(
            opts.candidateId,
          );
          if (!candidatePublication) {
            throw new Error(`Prompt Candidate publication not found: ${opts.candidateId}`);
          }
          const promotionPolicy = PromptPromotionPolicySchema.parse(
            JSON.parse(await readFile(opts.promotionPolicy, "utf-8")),
          );
          const authorizedPolicyHashes = new Set(
            required(
              undefined,
              "MOSAIC_PROMPT_PROMOTION_POLICY_HASHES",
              "MOSAIC_PROMPT_PROMOTION_POLICY_HASHES",
            )
              .split(",")
              .map((value) => value.trim())
              .filter(Boolean),
          );
          const promotionAuthorization = await authorizeStoredPromptPromotion({
            api,
            candidate,
            experimentId: opts.experimentId,
            policy: promotionPolicy,
            authorizedPolicyHashes,
            decidedAt: new Date().toISOString(),
          });
          const { decision: promotionDecision, releaseEnvironment } = promotionAuthorization;
          if (promotionDecision.decision !== "ELIGIBLE") {
            throw new Error("Prompt Promotion Authority rejected the Candidate");
          }
          if (opts.codeCommit !== releaseEnvironment.codeCommit) {
            throw new Error("prompt_release_authorized_code_commit_mismatch");
          }
          if (
            opts.executionBehaviorReleaseRef !==
            releaseEnvironment.executionBehaviorRelease.archive_ref
          ) {
            throw new Error("prompt_release_authorized_execution_behavior_ref_mismatch");
          }
          const manifest = await stagePromptRelease(
            {
              registryRoot: registryRoot(opts),
              releaseId: opts.releaseId,
              candidate,
              candidatePublication,
              promotionDecision,
              privatePromptRepo:
                opts.privatePromptsRepo?.trim() ||
                process.env.MOSAIC_PROMPTS_REPO?.trim() ||
                required(
                  process.env.MOSAIC_PRIVATE_PROMPT_REPO,
                  "MOSAIC_PRIVATE_PROMPT_REPO",
                  "--private-prompts-repo",
                ),
              privatePromptCommit: opts.privatePromptCommit,
              codeCommit: opts.codeCommit,
              executionBehaviorReleaseRef: opts.executionBehaviorReleaseRef,
              cohort: opts.cohort,
              accountMode: parseMode(opts.accountMode),
              approvalPolicyId: parsePolicy(opts.approvalPolicy),
            },
            {
              verifyPromotionDecision: async (candidateValue, decisionValue) => {
                if (
                  canonicalJsonHash(candidateValue) !== canonicalJsonHash(candidate) ||
                  canonicalJsonHash(decisionValue) !== canonicalJsonHash(promotionDecision)
                ) {
                  throw new Error("prompt_promotion_authority_binding_mismatch");
                }
                return releaseEnvironment;
              },
            },
          );
          console.log(
            `staged release=${manifest.release_id} base=${manifest.base_release_id ?? "none"} ` +
              `pairs=${manifest.prompt_pairs.length}`,
          );
        } catch (error) {
          reportError(error);
        } finally {
          await client.close();
        }
      },
    );

  command
    .command("build-baseline")
    .description(
      "Build a hash-closed active baseline manifest from exact commits and reviewed approval evidence.",
    )
    .requiredOption("--release-id <id>", "Immutable baseline release id")
    .requiredOption("--private-prompt-commit <hash>", "Exact private Prompt Git commit")
    .requiredOption("--code-commit <hash>", "Exact public code Git commit")
    .requiredOption(
      "--execution-behavior-release-ref <path>",
      "Immutable execution behavior archive ref at the public code commit",
    )
    .requiredOption("--approval-record <path>", "Reviewed baseline approval record JSON")
    .requiredOption("--out <path>", "Output active baseline manifest JSON")
    .option("--private-prompts-repo <path>", "Private prompt repository")
    .option("--code-repo <path>", "Public code repository")
    .option("--cohort <name>", "Release cohort", "cohort_default")
    .option("--account-mode <mode>", "paper | backtest | live", "paper")
    .action(
      async (opts: {
        releaseId: string;
        privatePromptCommit: string;
        codeCommit: string;
        executionBehaviorReleaseRef: string;
        approvalRecord: string;
        out: string;
        privatePromptsRepo?: string;
        codeRepo?: string;
        cohort: string;
        accountMode: string;
      }) => {
        try {
          const approvalRecord = PromptReleaseBaselineApprovalRecordSchema.parse(
            JSON.parse(await readFile(opts.approvalRecord, "utf-8")),
          );
          const manifest = await buildPromptReleaseBaselineManifest({
            releaseId: opts.releaseId,
            privatePromptRepo: required(
              opts.privatePromptsRepo,
              "MOSAIC_PROMPTS_REPO",
              "--private-prompts-repo",
            ),
            privatePromptCommit: opts.privatePromptCommit,
            codeCommit: opts.codeCommit,
            ...(opts.codeRepo?.trim() ? { codeRepo: opts.codeRepo.trim() } : {}),
            cohort: opts.cohort,
            accountMode: parseMode(opts.accountMode),
            executionBehaviorReleaseRef: opts.executionBehaviorReleaseRef,
            approvalRecord,
          });
          await mkdir(dirname(opts.out), { recursive: true });
          await writeFile(opts.out, `${JSON.stringify(manifest, null, 2)}\n`, "utf-8");
          console.log(`baseline manifest=${opts.out} pairs=${manifest.prompt_pairs.length}`);
        } catch (error) {
          reportError(error);
        }
      },
    );

  command
    .command("provision-baseline")
    .requiredOption("--manifest <path>", "Previously approved active baseline manifest")
    .requiredOption("--approved-by <operator>", "Authorized operator id")
    .requiredOption("--reason <text>", "Provisioning reason")
    .option("--registry-root <path>", "Release registry root")
    .option("--private-prompts-repo <path>", "Private prompt repository")
    .action(
      async (opts: {
        manifest: string;
        approvedBy: string;
        reason: string;
        registryRoot?: string;
        privatePromptsRepo?: string;
      }) => {
        try {
          const manifest = ActivePromptReleaseManifestSchema.parse(
            JSON.parse(await readFile(opts.manifest, "utf-8")),
          ) as ActivePromptReleaseManifest;
          await provisionPromptReleaseBaseline({
            registryRoot: registryRoot(opts),
            manifest,
            privatePromptRepo: required(
              opts.privatePromptsRepo,
              "MOSAIC_PROMPTS_REPO",
              "--private-prompts-repo",
            ),
            approvedBy: opts.approvedBy,
            reason: opts.reason,
          });
          console.log(`baseline release=${manifest.release_id} at=${manifest.activated_at}`);
        } catch (error) {
          reportError(error);
        }
      },
    );

  command
    .command("build-gate-d-bootstrap-manifest")
    .description("Build a staged v4 Gate-D anchor from the current active legacy release.")
    .requiredOption("--release-id <id>", "New Gate-D release id")
    .requiredOption("--created-at <iso>", "Deterministic manifest creation timestamp")
    .requiredOption("--full-bundle <path>", "Capability full-bundle JSON")
    .requiredOption("--receipt <path>", "Approved Gate-D receipt JSON")
    .requiredOption("--out <path>", "Output staged v4 manifest JSON")
    .option("--registry-root <path>", "Release registry root")
    .action(
      async (opts: {
        releaseId: string;
        createdAt: string;
        fullBundle: string;
        receipt: string;
        out: string;
        registryRoot?: string;
      }) => {
        try {
          const manifest = await buildKnotGateDBootstrapManifest({
            registryRoot: registryRoot(opts),
            releaseId: opts.releaseId,
            createdAt: z.iso.datetime({ offset: true }).parse(opts.createdAt),
            capabilityFullBundle: JSON.parse(await readFile(opts.fullBundle, "utf-8")),
            gateDReceipt: JSON.parse(await readFile(opts.receipt, "utf-8")),
          });
          await writeFile(opts.out, `${JSON.stringify(manifest, null, 2)}\n`, "utf-8");
          console.log(`built Gate-D release=${manifest.release_id}`);
        } catch (error) {
          reportError(error);
        }
      },
    );

  command
    .command("bootstrap-gate-d-stage")
    .description("Stage a reviewed, current-fixed-point Gate-D v4 manifest.")
    .requiredOption("--manifest <path>", "Reviewed staged Gate-D v4 manifest JSON")
    .option("--registry-root <path>", "Release registry root")
    .action(async (opts: { manifest: string; registryRoot?: string }) => {
      try {
        const manifest = JSON.parse(await readFile(opts.manifest, "utf-8")) as Record<
          string,
          unknown
        >;
        await stageKnotGateDBootstrapRelease({
          registryRoot: registryRoot(opts),
          manifest,
        });
        console.log(`staged Gate-D release=${String(manifest.release_id ?? "")}`);
      } catch (error) {
        reportError(error);
      }
    });

  command
    .command("canary")
    .requiredOption("--release-id <id>", "Release id")
    .requiredOption("--approved-by <operator>", "Authorized operator id")
    .requiredOption("--reason <text>", "Approval reason")
    .option("--traffic-percent <n>", "Canary traffic percentage", "10")
    .option("--registry-root <path>", "Release registry root")
    .action(
      async (opts: {
        releaseId: string;
        approvedBy: string;
        reason: string;
        trafficPercent: string;
        registryRoot?: string;
      }) => {
        try {
          const root = optionalRegistryRoot(opts);
          await assertTransitionOrGateDBootstrap("START_PROMPT_CANARY", root, opts.releaseId);
          const manifest = await startPromptReleaseCanary({
            registryRoot: registryRoot(opts),
            releaseId: opts.releaseId,
            approvedBy: opts.approvedBy,
            reason: opts.reason,
            trafficPercent: Number.parseFloat(opts.trafficPercent),
          });
          console.log(
            `canary release=${manifest.release_id} traffic=${manifest.activation_scope.traffic_percent}%`,
          );
        } catch (error) {
          reportError(error);
        }
      },
    );

  command
    .command("summarize-slo")
    .requiredOption("--release-id <id>", "Canary release id")
    .requiredOption("--observation-ended-at <timestamp>", "Closed observation end timestamp")
    .requiredOption("--out <path>", "Output SLO artifact JSON")
    .option("--registry-root <path>", "Release registry root")
    .action(
      async (opts: {
        releaseId: string;
        observationEndedAt: string;
        out: string;
        registryRoot?: string;
      }) => {
        try {
          const registry = new ActivePromptReleaseRegistry(registryRoot(opts));
          const manifest = await registry.load(opts.releaseId);
          if (!manifest) throw new Error("prompt_release_not_found");
          if (manifest.lifecycle_state !== "canary" || !manifest.canary_started_at) {
            throw new Error("prompt_release_slo_summary_requires_canary");
          }
          const eventLog = required(
            undefined,
            "MOSAIC_PROMPT_CANARY_EVENT_LOG",
            "MOSAIC_PROMPT_CANARY_EVENT_LOG",
          );
          const artifact = buildPromptReleaseCanarySloArtifact({
            releaseId: manifest.release_id,
            accountMode: manifest.activation_scope.account_mode,
            trafficPercent: manifest.activation_scope.traffic_percent,
            canaryStartedAt: manifest.canary_started_at,
            observationEndedAt: opts.observationEndedAt,
            stageSnapshotHashes: manifest.stage_snapshot_hashes,
            records: await new PromptReleaseCanaryEventJournal(eventLog).read(),
          });
          await mkdir(dirname(opts.out), { recursive: true });
          await writeFile(opts.out, `${JSON.stringify(artifact, null, 2)}\n`, "utf-8");
          console.log(
            `slo artifact=${artifact.artifact_hash} samples=${artifact.eligible_event_count}`,
          );
        } catch (error) {
          reportError(error);
        }
      },
    );

  command
    .command("activate")
    .requiredOption("--release-id <id>", "Release id")
    .requiredOption("--approved-by <operator>", "Authorized operator id")
    .requiredOption("--reason <text>", "Activation reason")
    .requiredOption("--slo-artifact <path>", "Aggregated canary SLO artifact JSON")
    .option("--registry-root <path>", "Release registry root")
    .action(
      async (opts: {
        releaseId: string;
        approvedBy: string;
        reason: string;
        sloArtifact: string;
        registryRoot?: string;
      }) => {
        try {
          const root = optionalRegistryRoot(opts);
          await assertTransitionOrGateDBootstrap("ACTIVATE_PROMPT_RELEASE", root, opts.releaseId);
          const manifest = await activatePromptRelease({
            registryRoot: registryRoot(opts),
            releaseId: opts.releaseId,
            approvedBy: opts.approvedBy,
            reason: opts.reason,
            sloArtifact: await parseSloArtifact(opts.sloArtifact),
          });
          console.log(`active release=${manifest.release_id} at=${manifest.activated_at}`);
        } catch (error) {
          reportError(error);
        }
      },
    );

  command
    .command("rollback")
    .requiredOption("--release-id <id>", "Release id")
    .requiredOption("--approved-by <operator>", "Authorized operator id")
    .requiredOption("--reason <text>", "Rollback reason")
    .option("--registry-root <path>", "Release registry root")
    .action(
      async (opts: {
        releaseId: string;
        approvedBy: string;
        reason: string;
        registryRoot?: string;
      }) => {
        try {
          const manifest = await rollbackPromptRelease({
            registryRoot: registryRoot(opts),
            releaseId: opts.releaseId,
            approvedBy: opts.approvedBy,
            reason: opts.reason,
          });
          console.log(`rolled_back release=${manifest.release_id} at=${manifest.rolled_back_at}`);
        } catch (error) {
          reportError(error);
        }
      },
    );

  command
    .command("status")
    .option("--release-id <id>", "Release id; defaults to active pointer")
    .option("--registry-root <path>", "Release registry root")
    .action(async (opts: { releaseId?: string; registryRoot?: string }) => {
      try {
        const registry = new ActivePromptReleaseRegistry(registryRoot(opts));
        const manifest = opts.releaseId
          ? await registry.load(opts.releaseId)
          : await registry.resolveActive();
        if (!manifest) throw new Error("prompt release not found");
        console.log(JSON.stringify(manifest, null, 2));
      } catch (error) {
        reportError(error);
      }
    });
}
