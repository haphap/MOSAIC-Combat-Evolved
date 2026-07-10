/**
 * `pnpm dev prompts` — prompt asset operations.
 *
 * The private prompt repo is intentionally separate from the project repo.
 * Autoresearch will later write optimized prompts there instead of committing
 * them under the project `prompts/mosaic/**` tree.
 */

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import type { Command } from "commander";
import pc from "picocolors";
import { parseResearchKnobsPrompt } from "../../agents/helpers/research_knobs.js";
import { promptPath } from "../../agents/prompts/cohorts.js";
import {
  buildDomainKnobCatalogArtifact,
  buildDomainKnobEvaluationContractArtifact,
  renderDomainKnobCatalogArtifact,
  renderDomainKnobEvaluationContractArtifact,
  validateDomainKnobCatalogArtifact,
  validateDomainKnobEvaluationContractArtifact,
} from "../../agents/prompts/domain_knob_catalog.js";
import {
  buildDomainKnobValueRegistry,
  domainKnobValueRegistryPath,
  readDomainKnobValueRegistryFile,
  renderDomainKnobValueRegistry,
  validateDomainKnobValueRegistry,
  writeDomainKnobValueRegistryFile,
} from "../../agents/prompts/domain_knob_registry.js";
import {
  buildPromptIrContract,
  promptIrPathForSpec,
  readPromptIrContractFile,
  renderPromptIrContract,
  validatePromptIrContractForSpec,
  writePromptIrContractFile,
} from "../../agents/prompts/prompt_ir_registry.js";
import { checkResearchKnobsPrompts } from "../../agents/prompts/research_knobs_checker.js";
import {
  buildRuntimeResearchKnobs,
  upsertResearchKnobsFence,
  upsertRuntimeEvidenceContract,
} from "../../agents/prompts/research_knobs_projection.js";
import {
  buildRuntimeAgentManifestArtifact,
  RUNTIME_AGENT_SPECS,
  renderRuntimeAgentManifestArtifact,
  validateRuntimeAgentManifestArtifact,
} from "../../agents/prompts/runtime_agent_spec.js";
import {
  appendKnobMutationMetadataLog,
  applyKnobPatchesToPromptPair,
  buildKnobMutationMetadata,
  type KnobMutation,
} from "../../autoresearch/mutator.js";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";
import { redactSensitiveText } from "../../security/redaction.js";

interface InitPrivateRepoOpts {
  seedBaseline?: boolean;
}

interface AuditVersionsOpts {
  cohort?: string;
  status?: string;
  agent?: string;
  limit?: string;
}

interface VerifyReleaseOpts {
  versionId: string;
  allowUnkept?: boolean;
}

interface GcWorktreesOpts {
  repoTarget?: "project_git" | "private_git" | "all";
  maxAgeHours?: string;
}

interface CheckResearchKnobsOpts {
  cohort?: string;
  promptsRoot?: string;
  privatePromptsRoot?: string;
  enabledAgents?: string;
  enabledStages?: string;
  json?: boolean;
}

interface SyncResearchKnobsOpts {
  cohort?: string;
  privatePromptsRoot: string;
  agents?: string;
  write?: boolean;
}

interface SyncPromptIrOpts {
  cohort?: string;
  privatePromptsRoot: string;
  agents?: string;
  write?: boolean;
}

interface DryRunKnobPatchOpts {
  cohort?: string;
  privatePromptsRoot: string;
  agent: string;
  metadataLog?: string;
  writeMetadata?: boolean;
}

interface ExportDomainKnobCatalogOpts {
  out?: string;
  json?: boolean;
}

export function registerPrompts(program: Command): void {
  const prompts = program.command("prompts").description("Manage prompt assets.");

  prompts
    .command("init-private-repo")
    .argument("<path>", "Path to an independent private prompt git repo")
    .description("Initialize a sparse private prompt repo outside the project checkout.")
    .option(
      "--seed-baseline",
      "Copy project baseline prompts into the private repo. Migration only; creates broad shadowing.",
      false,
    )
    .action(async (path: string, opts: InitPrivateRepoOpts) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        if (opts.seedBaseline) {
          console.warn(
            pc.yellow(
              "warning: --seed-baseline creates private overrides for all seeded prompts; future baseline fixes require drift sync.",
            ),
          );
        }
        await client.start();
        const result = await api.promptsInitPrivateRepo({
          path,
          seed_baseline: Boolean(opts.seedBaseline),
        });
        console.log(pc.green("private prompt repo initialized"));
        console.log(`repo: ${redactSensitiveText(result.repo_root, [result.repo_root])}`);
        console.log(`prompts: ${redactSensitiveText(result.prompts_root, [result.repo_root])}`);
        console.log(`commit: ${result.commit_hash}`);
        console.log(`mode: ${result.seeded ? "seeded baseline" : "sparse"}`);
      } catch (err) {
        reportError(err, client);
      } finally {
        await client.close();
      }
    });

  prompts
    .command("audit-versions")
    .description("List prompt version metadata without showing prompt content.")
    .option("--cohort <name>", "Filter by cohort")
    .option("--status <status>", "Filter by prompt version status")
    .option("--agent <name>", "Filter by agent")
    .option("--limit <n>", "Max rows (default 20)")
    .action(async (opts: AuditVersionsOpts) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        await client.start();
        const result = await api.promptsAuditVersions({
          ...(opts.cohort ? { cohort: opts.cohort } : {}),
          ...(opts.status ? { status: opts.status } : {}),
          ...(opts.agent ? { agent: opts.agent } : {}),
          ...(opts.limit ? { limit: Number.parseInt(opts.limit, 10) } : {}),
        });
        console.log(pc.bold("\nprompt versions"));
        if (result.versions.length === 0) {
          console.log(pc.dim("  no versions"));
        }
        for (const row of result.versions) {
          console.log(
            `  #${row.id} ${row.status} ${row.cohort}/${row.agent} ` +
              `prompt=${row.modification_commit_hash?.slice(0, 12) ?? "-"} ` +
              `code=${row.code_commit_hash?.slice(0, 12) ?? "-"}`,
          );
          console.log(
            pc.dim(
              `     repo=${row.prompt_repo_id ?? "-"} sha=${row.prompt_sha256?.slice(0, 12) ?? "-"} ` +
                `delta=${row.delta_sharpe ?? "n/a"} branch=${row.branch_name}`,
            ),
          );
        }
      } catch (err) {
        reportError(err, client);
      } finally {
        await client.close();
      }
    });

  prompts
    .command("verify-release")
    .requiredOption("--version-id <id>", "Prompt version id to verify")
    .option("--allow-unkept", "Do not require status=keep")
    .description("Verify prompt metadata, content hash, and compatibility before release.")
    .action(async (opts: VerifyReleaseOpts) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        await client.start();
        const result = await api.promptsVerifyRelease({
          version_id: Number.parseInt(opts.versionId, 10),
          require_kept: !opts.allowUnkept,
        });
        const color = result.ready ? pc.green : pc.red;
        console.log(color(`release ${result.ready ? "ready" : "blocked"}`));
        for (const [name, ok] of Object.entries(result.checks)) {
          console.log(`  ${ok ? pc.green("ok") : pc.red("no")} ${name}`);
        }
        console.log(
          pc.dim(
            `pin code=${result.pin.code_commit_hash?.slice(0, 12) ?? "-"} ` +
              `prompt=${result.pin.prompt_commit_hash?.slice(0, 12) ?? "-"} ` +
              `repo=${result.pin.prompt_repo_id ?? "-"} sha=${result.pin.prompt_sha256?.slice(0, 12) ?? "-"}`,
          ),
        );
        if (!result.ready) process.exitCode = 1;
      } catch (err) {
        reportError(err, client);
      } finally {
        await client.close();
      }
    });

  prompts
    .command("export-domain-knob-catalog")
    .description("Render the machine-readable domain knob catalog and runtime registries.")
    .option("--out <path>", "Write catalog JSON to a file")
    .option("--json", "Print catalog JSON to stdout")
    .action(async (opts: ExportDomainKnobCatalogOpts) => {
      const artifact = buildDomainKnobCatalogArtifact();
      const reasons = validateDomainKnobCatalogArtifact(artifact);
      if (reasons.length > 0) {
        throw new Error(`domain knob catalog failed self-check: ${reasons.join("; ")}`);
      }
      const rendered = renderDomainKnobCatalogArtifact(artifact);
      if (opts.out) {
        await mkdir(dirname(opts.out), { recursive: true });
        await writeFile(opts.out, rendered, "utf-8");
      }
      if (opts.json || !opts.out) {
        console.log(rendered.trimEnd());
      } else {
        console.log(`domain_knob_catalog: ${redactSensitiveText(opts.out).slice(0, 220)}`);
      }
    });

  prompts
    .command("export-runtime-agent-manifest")
    .description("Render the stage-aware runtime agent manifest.")
    .option("--out <path>", "Write manifest JSON to a file")
    .option("--json", "Print manifest JSON to stdout")
    .action(async (opts: ExportDomainKnobCatalogOpts) => {
      const artifact = buildRuntimeAgentManifestArtifact();
      const reasons = validateRuntimeAgentManifestArtifact(artifact);
      if (reasons.length > 0) {
        throw new Error(`runtime agent manifest failed self-check: ${reasons.join("; ")}`);
      }
      const rendered = renderRuntimeAgentManifestArtifact(artifact);
      if (opts.out) {
        await mkdir(dirname(opts.out), { recursive: true });
        await writeFile(opts.out, rendered, "utf-8");
      }
      if (opts.json || !opts.out) {
        console.log(rendered.trimEnd());
      } else {
        console.log(`runtime_agent_manifest: ${redactSensitiveText(opts.out).slice(0, 220)}`);
      }
    });

  prompts
    .command("export-domain-knob-evaluation-contract")
    .description("Render the language-neutral domain knob evaluation contract.")
    .option("--out <path>", "Write evaluation contract JSON to a file")
    .option("--json", "Print evaluation contract JSON to stdout")
    .action(async (opts: ExportDomainKnobCatalogOpts) => {
      const catalog = buildDomainKnobCatalogArtifact();
      const artifact = buildDomainKnobEvaluationContractArtifact(catalog);
      const reasons = validateDomainKnobEvaluationContractArtifact(artifact, catalog);
      if (reasons.length > 0) {
        throw new Error(`domain knob evaluation contract failed self-check: ${reasons.join("; ")}`);
      }
      const rendered = renderDomainKnobEvaluationContractArtifact(artifact);
      if (opts.out) {
        await mkdir(dirname(opts.out), { recursive: true });
        await writeFile(opts.out, rendered, "utf-8");
      }
      if (opts.json || !opts.out) {
        console.log(rendered.trimEnd());
      } else {
        console.log(
          `domain_knob_evaluation_contract: ${redactSensitiveText(opts.out).slice(0, 220)}`,
        );
      }
    });

  prompts
    .command("check-research-knobs")
    .description("Validate research-knobs fences for enabled runtime agents.")
    .option("--cohort <name>", "Cohort to check (default cohort_default)")
    .option("--prompts-root <path>", "Bundled/baseline prompts root override")
    .option("--private-prompts-root <path>", "Private prompts root override")
    .option(
      "--enabled-agents <list>",
      "Comma-separated agent ids to fail-closed check; '*' checks all 25. Defaults to all agents for private prompts, otherwise MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS.",
    )
    .option(
      "--enabled-stages <list>",
      "Comma-separated agent:stage ids; '*' checks all declared runtime stages.",
    )
    .option("--json", "Print the full machine-readable report")
    .action(async (opts: CheckResearchKnobsOpts) => {
      const enabledAgents =
        opts.enabledAgents !== undefined
          ? new Set(
              opts.enabledAgents
                .split(",")
                .map((item) => item.trim())
                .filter(Boolean),
            )
          : undefined;
      const enabledAgentStages =
        opts.enabledStages !== undefined
          ? new Set(
              opts.enabledStages
                .split(",")
                .map((item) => item.trim())
                .filter(Boolean),
            )
          : undefined;
      try {
        const result = await checkResearchKnobsPrompts({
          cohort: opts.cohort ?? "cohort_default",
          ...(opts.promptsRoot ? { promptsRoot: opts.promptsRoot } : {}),
          ...(opts.privatePromptsRoot ? { privatePromptsRoot: opts.privatePromptsRoot } : {}),
          ...(enabledAgents ? { enabledAgents } : {}),
          ...(enabledAgentStages ? { enabledAgentStages } : {}),
        });
        if (opts.json) {
          console.log(JSON.stringify(result, null, 2));
        } else {
          const color = result.ready ? pc.green : pc.red;
          console.log(
            color(
              `research-knobs ${result.ready ? "ready" : "blocked"} ` +
                `enabled_stages=${result.enabled_agent_stages.length} ` +
                `legacy_stages=${result.legacy_agent_stages.length}`,
            ),
          );
          for (const row of result.rows.filter(
            (item) => item.enabled || item.status === "failed",
          )) {
            const marker = row.ready ? pc.green("ok") : row.enabled ? pc.red("no") : pc.dim("--");
            console.log(
              `  ${marker} ${row.layer}/${row.agent}:${row.stage} ${row.status}` +
                (row.snapshot_hash ? ` ${row.snapshot_hash.slice(0, 19)}` : ""),
            );
            for (const reason of row.reasons) {
              console.log(pc.dim(`     ${redactSensitiveText(reason).slice(0, 220)}`));
            }
          }
        }
        if (!result.ready) process.exitCode = 1;
      } catch (err) {
        console.error(pc.red(`error: ${redactSensitiveText((err as Error).message)}`));
        process.exitCode = 1;
      }
    });

  prompts
    .command("sync-research-knobs")
    .description("Generate/update research-knobs fences and runtime evidence contracts.")
    .requiredOption("--private-prompts-root <path>", "Private prompts root to update")
    .option("--cohort <name>", "Cohort to update (default cohort_default)")
    .option("--agents <list>", "Comma-separated agent ids; defaults to all runtime agents")
    .option("--write", "Write changes. Without this, only reports pending updates.", false)
    .action(async (opts: SyncResearchKnobsOpts) => {
      const cohort = opts.cohort ?? "cohort_default";
      const selected = opts.agents
        ? new Set(
            opts.agents
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean),
          )
        : null;
      const specs = RUNTIME_AGENT_SPECS.filter((spec) => !selected || selected.has(spec.agent));
      const changed: string[] = [];
      for (const spec of specs) {
        const registryPath = domainKnobValueRegistryPath({
          privatePromptsRoot: opts.privatePromptsRoot,
          cohort,
          agent: spec.agent,
        });
        const existingRegistry = await readDomainKnobValueRegistryFile(registryPath);
        const registry = buildDomainKnobValueRegistry(spec, cohort, { existing: existingRegistry });
        const registryReasons = validateDomainKnobValueRegistry(spec, registry, cohort);
        if (registryReasons.length > 0) {
          throw new Error(`${spec.agent}: ${registryReasons.join("; ")}`);
        }
        const renderedRegistry = renderDomainKnobValueRegistry(registry);
        const currentRegistry = existingRegistry
          ? renderDomainKnobValueRegistry(existingRegistry)
          : "";
        if (renderedRegistry !== currentRegistry) {
          changed.push(registryPath);
          if (opts.write) {
            await writeDomainKnobValueRegistryFile(registryPath, registry);
          }
        }
        const knobs = buildRuntimeResearchKnobs(spec, { domainRegistry: registry });
        for (const language of ["zh", "en"] as const) {
          const path = promptPath({
            agent: spec.agent,
            layer: spec.layer,
            cohort,
            language,
            promptsRoot: opts.privatePromptsRoot,
          });
          const current = await readFile(path, "utf-8");
          const next = upsertRuntimeEvidenceContract(
            upsertResearchKnobsFence(current, knobs),
            spec,
            language,
          );
          if (next === current) continue;
          changed.push(path);
          if (opts.write) {
            await mkdir(dirname(path), { recursive: true });
            await writeFile(path, next, "utf-8");
          }
        }
      }
      const label = opts.write ? "updated" : "pending";
      console.log(`${label} research-knobs files: ${changed.length}`);
      for (const path of changed.slice(0, 50)) {
        console.log(`  ${redactSensitiveText(path).slice(0, 220)}`);
      }
      if (changed.length > 50) console.log(`  ... ${changed.length - 50} more`);
    });

  prompts
    .command("sync-prompt-ir")
    .description("Generate/update Prompt IR contracts from runtime agent specs.")
    .requiredOption("--private-prompts-root <path>", "Private prompts root to update")
    .option("--cohort <name>", "Cohort to update (default cohort_default)")
    .option("--agents <list>", "Comma-separated agent ids; defaults to all runtime agents")
    .option("--write", "Write changes. Without this, only reports pending updates.", false)
    .action(async (opts: SyncPromptIrOpts) => {
      const cohort = opts.cohort ?? "cohort_default";
      const selected = opts.agents
        ? new Set(
            opts.agents
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean),
          )
        : null;
      const specs = RUNTIME_AGENT_SPECS.filter((spec) => !selected || selected.has(spec.agent));
      const changed: string[] = [];
      for (const spec of specs) {
        const path = promptIrPathForSpec({ privatePromptsRoot: opts.privatePromptsRoot, spec });
        const existing = await readPromptIrContractFile(path).catch(() => null);
        const contract = buildPromptIrContract(spec, cohort);
        const reasons = validatePromptIrContractForSpec(contract, spec, cohort);
        if (reasons.length > 0) {
          throw new Error(`${spec.agent}: ${reasons.join("; ")}`);
        }
        const rendered = renderPromptIrContract(contract);
        const current = existing ? renderPromptIrContract(existing) : "";
        if (rendered !== current) {
          changed.push(path);
          if (opts.write) {
            await writePromptIrContractFile(path, contract);
          }
        }
      }
      const label = opts.write ? "updated" : "pending";
      console.log(`${label} prompt-ir files: ${changed.length}`);
      for (const path of changed.slice(0, 50)) {
        console.log(`  ${redactSensitiveText(path).slice(0, 220)}`);
      }
      if (changed.length > 50) console.log(`  ... ${changed.length - 50} more`);
    });

  prompts
    .command("dry-run-knob-patch")
    .description("Generate a legal parameter-level knob patch and assemble prompt projections.")
    .requiredOption("--private-prompts-root <path>", "Private prompts root")
    .requiredOption("--agent <name>", "Agent id to mutate")
    .option("--cohort <name>", "Cohort to read (default cohort_default)")
    .option("--metadata-log <path>", "JSONL mutation metadata log path")
    .option("--write-metadata", "Append dry-run metadata to the mutation log", false)
    .action(async (opts: DryRunKnobPatchOpts) => {
      const cohort = opts.cohort ?? "cohort_default";
      const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === opts.agent);
      if (!spec) throw new Error(`unknown runtime agent: ${opts.agent}`);
      const zhPath = promptPath({
        agent: spec.agent,
        layer: spec.layer,
        cohort,
        language: "zh",
        promptsRoot: opts.privatePromptsRoot,
      });
      const enPath = promptPath({
        agent: spec.agent,
        layer: spec.layer,
        cohort,
        language: "en",
        promptsRoot: opts.privatePromptsRoot,
      });
      const [zhPrompt, enPrompt] = await Promise.all([
        readFile(zhPath, "utf-8"),
        readFile(enPath, "utf-8"),
      ]);
      const baseKnobs = parseResearchKnobsPrompt(zhPrompt).knobs;
      const target = baseKnobs.mutation_targets.find((item) =>
        item.path.includes("/confidence_policy/missing_current_data/cap"),
      );
      if (!target) throw new Error(`${opts.agent}: missing confidence cap mutation target`);
      const oldValue = baseKnobs.confidence_caps.missing_current_data?.cap;
      if (typeof oldValue !== "number") {
        throw new Error(`${opts.agent}: missing_current_data cap is not numeric`);
      }
      const step = target.step ?? 0.05;
      const min = target.min ?? 0;
      const newValue = Math.max(min, Number((oldValue - step).toFixed(10)));
      const mutation: KnobMutation = {
        prediction_target: baseKnobs.prediction_targets[0]?.id ?? "primary",
        evaluation_metric: "confidence_calibration_error",
        horizon: "5d",
        rollback_condition: {
          metric: "confidence_calibration_error",
          worse_by: 0.03,
          unit: "ratio",
        },
        knob_patches: [
          {
            path: target.path,
            old_value: oldValue,
            new_value: newValue,
            rationale: "Dry-run cap tightening to test parameter-level mutation plumbing.",
            expected_effect: "Reduce overconfident outputs when required current data is missing.",
          },
        ],
        renormalization: [],
        risk: "May understate confidence when missing-data flags are noisy.",
      };
      const assembled = applyKnobPatchesToPromptPair(zhPrompt, enPrompt, mutation);
      const metadata = buildKnobMutationMetadata({
        mutationId: `KM-${Date.now()}`,
        agent: opts.agent,
        cohort,
        baseKnobs,
        newKnobs: assembled.knobs,
        mutation,
        decision: "dry_run",
      });
      if (opts.writeMetadata) {
        const logPath =
          opts.metadataLog ??
          `${dirname(dirname(opts.privatePromptsRoot))}/mutation_patches/knob_mutations.jsonl`;
        await appendKnobMutationMetadataLog({ logPath, metadata });
        console.log(`metadata_log: ${redactSensitiveText(logPath).slice(0, 220)}`);
      }
      console.log(
        `dry-run knob patch ${opts.agent}: ${oldValue.toFixed(2)} -> ${newValue.toFixed(2)} ` +
          `prompt_chars=${assembled.zh_prompt.length + assembled.en_prompt.length} ` +
          `metadata=${metadata.mutation_id}`,
      );
    });

  prompts
    .command("gc-worktrees")
    .description("Remove stale managed project/private prompt worktrees.")
    .option("--repo-target <target>", "project_git | private_git | all (default all)")
    .option("--max-age-hours <n>", "Remove worktrees older than this many hours (default 24)")
    .action(async (opts: GcWorktreesOpts) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        await client.start();
        const result = await api.autoresearchGcWorktrees({
          ...(opts.repoTarget ? { repo_target: opts.repoTarget } : {}),
          ...(opts.maxAgeHours ? { max_age_hours: Number(opts.maxAgeHours) } : {}),
        });
        for (const row of result.results) {
          console.log(
            `${row.repo_target}: removed=${row.removed.length} kept=${row.kept.length}` +
              ` skipped=${row.skipped?.length ?? 0}` +
              (row.skipped_reason
                ? ` (${row.skipped_reason})`
                : row.missing
                  ? " (no worktree dir)"
                  : ""),
          );
        }
      } catch (err) {
        reportError(err, client);
      } finally {
        await client.close();
      }
    });
}

function reportError(err: unknown, client: BridgeClient): void {
  if (err instanceof RpcError) {
    console.error(pc.red(`bridge error [${err.code}]: ${redactSensitiveText(err.message)}`));
  } else {
    console.error(pc.red(`error: ${redactSensitiveText((err as Error).message)}`));
  }
  const tail = client.stderrTail?.trim();
  if (tail) console.error(pc.dim(redactSensitiveText(tail).slice(-1500)));
  process.exitCode = 1;
}
