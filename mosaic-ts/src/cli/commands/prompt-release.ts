import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import type { Command } from "commander";
import {
  type ActivePromptReleaseManifest,
  ActivePromptReleaseManifestSchema,
} from "../../agents/prompts/prompt_release_contract.js";
import {
  buildPromptReleaseCanarySloArtifact,
  PromptReleaseCanaryEventJournal,
  type PromptReleaseCanarySloArtifact,
  PromptReleaseCanarySloArtifactSchema,
} from "../../autoresearch/prompt_release_canary_slo.js";
import {
  activatePromptRelease,
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
    .requiredOption("--version-id <id>", "Kept domain mutation version id")
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
        versionId: string;
        releaseId: string;
        registryRoot?: string;
        privatePromptsRepo?: string;
        cohort: string;
        accountMode: string;
        approvalPolicy: string;
      }) => {
        const client = new BridgeClient();
        const api = new BridgeApi(client);
        try {
          await client.start();
          const verification = await api.promptsVerifyRelease({
            version_id: Number.parseInt(opts.versionId, 10),
            require_kept: true,
          });
          const manifest = await stagePromptRelease({
            registryRoot: registryRoot(opts),
            releaseId: opts.releaseId,
            verification,
            privatePromptRepo:
              opts.privatePromptsRepo?.trim() ||
              process.env.MOSAIC_PROMPTS_REPO?.trim() ||
              required(
                process.env.MOSAIC_PRIVATE_PROMPT_REPO,
                "MOSAIC_PRIVATE_PROMPT_REPO",
                "--private-prompts-repo",
              ),
            cohort: opts.cohort,
            accountMode: parseMode(opts.accountMode),
            approvalPolicyId: parsePolicy(opts.approvalPolicy),
          });
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
