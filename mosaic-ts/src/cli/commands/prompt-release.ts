import { readFile } from "node:fs/promises";
import type { Command } from "commander";
import {
  activatePromptRelease,
  type RuntimeSloMeasurements,
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

async function parseSloMeasurements(path: string): Promise<RuntimeSloMeasurements> {
  const value = JSON.parse(await readFile(path, "utf-8")) as Record<string, unknown>;
  const { passed: _ignored, ...measurements } = value;
  return measurements as unknown as RuntimeSloMeasurements;
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
    .command("activate")
    .requiredOption("--release-id <id>", "Release id")
    .requiredOption("--approved-by <operator>", "Authorized operator id")
    .requiredOption("--reason <text>", "Activation reason")
    .requiredOption("--slo-summary <path>", "Measured runtime SLO summary JSON")
    .option("--registry-root <path>", "Release registry root")
    .action(
      async (opts: {
        releaseId: string;
        approvedBy: string;
        reason: string;
        sloSummary: string;
        registryRoot?: string;
      }) => {
        try {
          const manifest = await activatePromptRelease({
            registryRoot: registryRoot(opts),
            releaseId: opts.releaseId,
            approvedBy: opts.approvedBy,
            reason: opts.reason,
            measurements: await parseSloMeasurements(opts.sloSummary),
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
