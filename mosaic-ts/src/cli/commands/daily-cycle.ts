/**
 * Phase 2F MVP CLI command: ``pnpm dev daily-cycle``.
 *
 * Drives one full L1→L2→L3→L4 cycle via the composite graph from
 * ``graph/daily_cycle.ts``. Covers three LLM modes:
 *
 *   1. ``--fake-llm``: in-memory canned mock plus explicitly marked synthetic
 *      bridge fixtures. Validates wiring without LLM or live-data cost.
 *   2. ``--structured-smoke``: real LLM + bundled prompts, with every
 *      production ledger/release writer disabled.
 *   3. Default: real LLM via createLlmFromConfig (lemonade by default
 *      when LEMONADE_BASE_URL is set; otherwise the bridge config's
 *      provider).
 *
 * The CLI surface is intentionally thin — every layer's logic is already
 * unit-tested in test/{macro,sector,superinvestor,decision,daily_cycle}*.
 */

import { createHash } from "node:crypto";
import { lstatSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { relative, resolve } from "node:path";
import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import type { BaseMessage } from "@langchain/core/messages";
import { AIMessage } from "@langchain/core/messages";
import type { Command } from "commander";
import pc from "picocolors";
import { AcceptedAgentOutputStore } from "../../agents/accepted_output.js";
import {
  type AgentDisplayNarrativeBundle,
  buildAgentDisplayNarrativeBundle,
} from "../../agents/agent_display_narrative.js";
import { assertStructuredOutputCapability } from "../../agents/helpers/agent_run_contract.js";
import { buildPositionAuditToolStatusSummary } from "../../agents/helpers/position_audit.js";
import { privateKnotRuntimeInstalled } from "../../agents/helpers/private_knot_boundary.js";
import {
  formatDurationMs,
  parseAgentTimeoutSeconds,
  resolveAgentTimeoutMs,
} from "../../agents/helpers/runtime.js";
import { findBundledPromptsRoot, formatPromptSourceLabel } from "../../agents/prompts/cohorts.js";
import { PRIVATE_KNOT_COHORT_IDS } from "../../agents/prompts/private_knot_stage_enablement.js";
import { assertRuntimePromptPreflight } from "../../agents/prompts/runtime_prompt_preflight.js";
import { captureDailyCycleRkeFootprints } from "../../agents/rke_footprints.js";
import { type DailyCycleStateType, emptyCurrentPositions } from "../../agents/state.js";
import type {
  CurrentPosition,
  CurrentPositionsSnapshot,
  PortfolioAction,
  PositionAudit,
} from "../../agents/types.js";
import { loadExecutionBehaviorReleaseManifest } from "../../autoresearch/execution_behavior_release.js";
import { parseOutcomeStageSkips } from "../../autoresearch/outcome_stage_skip.js";
import {
  buildDarwinianRuntimeBinding,
  validateComponentWeightRuntimeSnapshot,
} from "../../autoresearch/production_variant.js";
import { assertAcceptedDailyCycle } from "../../backtest/decision_health.js";
import {
  BridgeApi,
  BridgeClient,
  type PaperOrderResult,
  type PaperSuggestion,
  RpcError,
} from "../../bridge/index.js";
import { buildDailyCycleGraph } from "../../graph/daily_cycle.js";
import { createLlmFromConfig, type LlmHandle } from "../../llm/factory.js";
import { redactSensitiveText } from "../../security/redaction.js";
import { pad } from "../_format.js";
import { fakeAgentStructuredOutput, fakeSchemaValue } from "../fake_agent_output.js";
import { applyPromptSourceOverrides } from "../prompt-source.js";

interface DailyCycleOptions {
  cohort?: string;
  date?: string;
  fakeLlm?: boolean;
  structuredSmoke?: boolean;
  llmProvider?: string;
  model?: string;
  baseUrl?: string;
  promptsRepo?: string;
  promptsRoot?: string;
  out?: string;
  vetoThreshold?: string;
  agentTimeoutSeconds?: string;
  maxTokens?: string;
  paperPositions?: boolean;
  currentPositionsJson?: string;
  currentPositionsFile?: string;
  paperExecuteDeltas?: boolean;
}

export interface PaperDeltaExecution {
  ticker: string;
  current_weight: number;
  target_weight: number;
  required_delta_weight: number;
  residual_drift_weight: number;
  order_intent_key: string | null;
  suggested_order: PaperSuggestion | null;
  submitted_order: PaperOrderResult | null;
  final_target_hash?: string;
  final_target_position_snapshot_hash?: string;
  base_account_snapshot_hash?: string;
  post_submit_snapshot_hash?: string;
  skipped_reason?: string;
}

export function registerDailyCycle(program: Command): void {
  program
    .command("daily-cycle")
    .description(
      "Run one MOSAIC daily cycle: L1 macro → L2 sector → L3 superinvestor → L4 decision. " +
        "Use --fake-llm for zero-cost smoke; default uses the bridge's configured LLM provider.",
    )
    .option("--cohort <name>", "Cohort id (default cohort_default)", "cohort_default")
    .option("--date <YYYY-MM-DD>", "as_of_date (default today)")
    .option("--fake-llm", "Use a canned mock LLM with non-production synthetic fixtures")
    .option(
      "--structured-smoke",
      "Use a real structured-output LLM with bundled prompts and no production writes",
    )
    .option("--llm-provider <name>", "Override LLM provider from bridge config")
    .option("--model <name>", "Override LLM model id (e.g. local Lemonade Qwen)")
    .option("--base-url <url>", "Override LLM base URL (e.g. http://127.0.0.1:8020/api/v0)")
    .option("--prompts-repo <path>", "Use a private prompt git repo for this run")
    .option("--prompts-root <path>", "Use a direct prompts/mosaic root for this run")
    .option("--out <path>", "Write the final state JSON to <path> instead of pretty-printing")
    .option(
      "--veto-threshold <num>",
      "CRO veto threshold; rejection rate > this triggers replay (default 0.5)",
    )
    .option(
      "--agent-timeout-seconds <seconds>",
      "Per-agent wall-clock timeout in seconds (default 300; 0/off disables)",
    )
    .option("--max-tokens <count>", "Per-request completion cap (structured-smoke default 8192)")
    .option("--paper-positions", "Seed current_positions from the active paper account")
    .option("--current-positions-json <json>", "Seed current_positions from an inline JSON fixture")
    .option("--current-positions-file <path>", "Seed current_positions from a JSON fixture file")
    .option(
      "--paper-execute-deltas",
      "Submit paper orders after the run using paper.suggest_order_from_signal target-current deltas",
    )
    .action(async (opts: DailyCycleOptions) => {
      const inheritedRuntimeEnv = {
        sourceGapBypass: process.env.MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS,
        fixtureBundleHash: process.env.MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH,
        knotRuntimeRoot: process.env.MOSAIC_KNOT_RUNTIME_ROOT,
      };
      let client: BridgeClient | null = null;
      try {
        if (opts.fakeLlm && opts.structuredSmoke) {
          throw new Error("--fake-llm and --structured-smoke are mutually exclusive");
        }
        const nonProductionSmoke = Boolean(opts.fakeLlm || opts.structuredSmoke);
        const asOfDate = opts.date ?? new Date().toISOString().slice(0, 10);
        assertDailyCyclePromptSourceMode(opts, nonProductionSmoke);
        if (nonProductionSmoke && opts.promptsRepo) {
          throw new Error(
            "non-production smoke must use bundled prompts, not a private prompt repo",
          );
        }
        const runtimePromptsRoot = nonProductionSmoke
          ? (opts.promptsRoot ?? findBundledPromptsRoot())
          : opts.promptsRoot;
        if (nonProductionSmoke && !runtimePromptsRoot) {
          throw new Error("bundled prompts are unavailable for non-production smoke");
        }
        if (nonProductionSmoke) {
          applyPromptSourceOverrides({ promptsRoot: runtimePromptsRoot as string });
        } else {
          applyPromptSourceOverrides(opts);
        }
        const sourceGapBypass = nonProductionSourceGapBypass(opts);
        let fixtureBundleHash: string | null = null;
        if (sourceGapBypass) {
          const fixtureBundle = validateStructuredSmokeFixtureBundle(asOfDate);
          fixtureBundleHash = fixtureBundle.bundleHash;
          process.env.MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS = sourceGapBypass;
          process.env.MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH = fixtureBundle.bundleHash;
          delete process.env.MOSAIC_KNOT_RUNTIME_ROOT;
        } else {
          delete process.env.MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS;
          delete process.env.MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH;
        }

        // BridgeClient snapshots its child environment in the constructor, so
        // construct it only after the production/non-production boundary above.
        client = new BridgeClient();
        const api = new BridgeApi(client);
        await client.start();
        const config = await api.configGet();
        const maxTokens = opts.maxTokens
          ? Number.parseInt(opts.maxTokens, 10)
          : opts.structuredSmoke
            ? 8192
            : undefined;
        if (maxTokens !== undefined && (!Number.isInteger(maxTokens) || maxTokens <= 0)) {
          throw new Error("--max-tokens must be a positive integer");
        }

        const llmHandle: LlmHandle = opts.fakeLlm
          ? buildFakeLlmHandle()
          : createLlmFromConfig(config, {
              tier: "deep",
              ...(opts.structuredSmoke ? { temperature: 0 } : {}),
              ...(opts.llmProvider ? { provider: opts.llmProvider } : {}),
              ...(opts.model ? { model: opts.model } : {}),
              ...(opts.baseUrl ? { baseUrl: opts.baseUrl } : {}),
              ...(maxTokens ? { maxTokens } : {}),
            });

        console.log(
          pc.dim(
            redactSensitiveText(
              `provider=${llmHandle.provider} model=${llmHandle.model}` +
                (llmHandle.baseUrl ? ` base=${llmHandle.baseUrl}` : "") +
                (opts.fakeLlm ? " (fake-llm)" : opts.structuredSmoke ? " (structured-smoke)" : ""),
            ),
          ),
        );
        console.log(
          pc.dim(
            redactSensitiveText(
              nonProductionSmoke
                ? "prompts=bundled-non-production"
                : `prompts=${formatPromptSourceLabel()}`,
            ),
          ),
        );

        const cohort = resolveDailyCycleCohort(opts, config);
        if (nonProductionSmoke && opts.paperExecuteDeltas) {
          throw new Error("non-production smoke cannot submit paper orders");
        }
        const vetoThreshold = opts.vetoThreshold ? Number(opts.vetoThreshold) : 0.5;
        const agentTimeoutSeconds = parseAgentTimeoutSeconds(opts.agentTimeoutSeconds);
        const agentTimeoutMs = resolveAgentTimeoutMs(agentTimeoutSeconds);
        const onAgentLog = (msg: string) => {
          console.log(pc.dim(`  ${redactSensitiveText(msg)}`));
        };
        const currentPositions = await loadDailyCycleCurrentPositions(opts, api);
        await assertStructuredOutputCapability(llmHandle.llm);
        const promptSource = nonProductionSmoke
          ? null
          : await api.promptsPreflight({ cohort, langs: ["zh", "en"] });
        if (promptSource && !promptSource.ready) {
          throw new Error(
            `prompt source preflight failed: ${promptSource.source_status.blocked_reason || "unknown"}`,
          );
        }
        const executionBehaviorRelease = nonProductionSmoke
          ? null
          : loadExecutionBehaviorReleaseManifest(
              resolve(
                findBundledPromptsRoot(),
                "..",
                "..",
                "registry",
                "prompt_checks",
                "execution_behavior_release_manifest_v1.json",
              ),
            );
        await assertRuntimePromptPreflight({
          cohort,
          requirePrivateKnot: !nonProductionSmoke,
          ...(runtimePromptsRoot ? { promptsRoot: runtimePromptsRoot } : {}),
        });
        if (nonProductionSmoke && privateKnotRuntimeInstalled()) {
          throw new Error("non-production smoke must not install a private KNOT runtime");
        }
        const asOfTimestamp = `${asOfDate}T15:00:00+08:00`;
        let darwinianRuntimeBinding = null;
        if (!nonProductionSmoke) {
          if (!promptSource || !executionBehaviorRelease) {
            throw new Error("live execution requires pinned prompt and behavior releases");
          }
          darwinianRuntimeBinding = buildDarwinianRuntimeBinding({
            cohortId: cohort,
            config,
            llmHandle,
            promptPreflight: promptSource,
            executionBehaviorRelease,
            effectiveAt: asOfTimestamp,
          });
        }
        const preparedDarwinian = darwinianRuntimeBinding
          ? await api.darwinianPrepareVariant(darwinianRuntimeBinding, asOfTimestamp)
          : null;
        const componentWeightSnapshot = preparedDarwinian
          ? validateComponentWeightRuntimeSnapshot(
              preparedDarwinian.component_weight_snapshot,
              preparedDarwinian.runtime_binding,
              asOfTimestamp,
            )
          : null;
        const rosterRevisionId =
          preparedDarwinian?.roster_revision.production_variant_roster_revision_id;
        if (preparedDarwinian && typeof rosterRevisionId !== "string") {
          throw new Error("Darwinian preparation did not return a roster revision ID");
        }
        const traceId = nonProductionSmoke
          ? `${opts.fakeLlm ? "fake" : "structured"}-smoke-${Date.now()}`
          : `daily-${createHash("sha256")
              .update(`${cohort}\u0000${asOfDate}\u0000${rosterRevisionId}`)
              .digest("hex")
              .slice(0, 24)}`;
        const preparedOutcomes = preparedDarwinian
          ? await api.darwinianPrepareDailyCycleOutcomes({
              production_variant_roster_revision_id: rosterRevisionId as string,
              graph_run_id: traceId,
              as_of: asOfTimestamp,
              prepared_at: asOfTimestamp,
            })
          : null;
        if (preparedOutcomes && preparedOutcomes.run_blockers.length > 0) {
          throw new Error(
            `outcome pre-run blocked: ${preparedOutcomes.run_blockers
              .map((row) => `${row.agent_id}:${row.reason}`)
              .join(",")}`,
          );
        }

        const acceptedOutputStore = new AcceptedAgentOutputStore();
        const graph = buildDailyCycleGraph({
          llmHandle,
          api,
          config,
          vetoThreshold,
          acceptedOutputStore,
          onLog: onAgentLog,
          ...(agentTimeoutSeconds !== undefined ? { agentTimeoutSeconds } : {}),
        });

        const initialState: DailyCycleStateType = {
          messages: [],
          active_cohort: cohort,
          as_of_date: asOfDate,
          mode: "live",
          trace_id: traceId,
          darwinian_runtime_binding: preparedDarwinian?.runtime_binding ?? null,
          darwinian_weight_snapshot: preparedDarwinian?.weight_snapshot ?? null,
          component_weight_snapshot: componentWeightSnapshot,
          outcome_schedule_plan: preparedOutcomes?.outcome_schedule_plan ?? null,
          outcome_stage_skips: parseOutcomeStageSkips(preparedOutcomes?.stage_skips ?? {}),
          accepted_output_refs: {},
          continuity_context: {},
          lesson_context: {},
          method_context: {},
          layer1_outputs: {},
          component_calibration_inputs: {},
          macro_input_gate: null,
          layer2_outputs: {},
          layer3_outputs: {},
          layer4_outputs: {
            cro: null,
            alpha_discovery: null,
            autonomous_execution: null,
            cio: null,
          },
          current_positions: currentPositions,
          position_reviews: [],
          position_audit: positionAuditFromSnapshot(currentPositions),
          portfolio_actions: [],
          replay_triggered: false,
          llm_calls: [],
        };

        console.log(pc.bold(`\nMOSAIC daily cycle — cohort=${cohort} date=${asOfDate}`));
        console.log(
          pc.dim(`agent_timeout=${agentTimeoutMs > 0 ? formatDurationMs(agentTimeoutMs) : "off"}`),
        );
        const t0 = Date.now();
        const final = (await graph.invoke(initialState)) as DailyCycleStateType;
        assertAcceptedDailyCycle(final);
        const agentDisplayNarratives = buildAgentDisplayNarrativeBundle(final, acceptedOutputStore);
        const agentRunAudits = final.llm_calls.flatMap((call) =>
          call.agent_run_audit ? [call.agent_run_audit] : [],
        );
        const stageSkipCount = Object.keys(final.outcome_stage_skips).length;
        const localSmokeStageSkipCount = nonProductionSmoke
          ? new Set(
              (final.layer4_outputs.runtime?.stage_trace ?? [])
                .filter((entry) => entry.operation === "stage_skip")
                .map((entry) => entry.stage),
            ).size
          : 0;
        if (agentRunAudits.length + stageSkipCount + localSmokeStageSkipCount !== 29) {
          throw new Error(
            "accepted daily cycle must expose exactly 29 accepted-or-skipped Agent stages; " +
              `got accepted=${agentRunAudits.length} skipped=${stageSkipCount + localSmokeStageSkipCount}`,
          );
        }
        const decisionDisposition = final.layer4_outputs.cio?.decision_disposition;
        if (!decisionDisposition) {
          throw new Error("accepted daily cycle is missing CIO decision_disposition");
        }
        if (!nonProductionSmoke) {
          const scorecardWrite = await api.scorecardAppend({
            active_cohort: final.active_cohort,
            as_of_date: final.as_of_date,
            trace_id: final.trace_id,
            mode: "live",
            darwinian_runtime_binding: final.darwinian_runtime_binding,
            outcome_schedule_plan: final.outcome_schedule_plan,
            outcome_stage_skips: final.outcome_stage_skips,
            accepted_output_refs: final.accepted_output_refs,
            accepted_output_records: acceptedOutputStore.records(),
            component_calibration_inputs: final.component_calibration_inputs,
            macro_input_gate: final.macro_input_gate,
            final_target_state: final.layer4_outputs.runtime?.final_target_state ?? null,
            portfolio_actions: final.portfolio_actions,
            agent_run_audits: agentRunAudits,
            decision_disposition: decisionDisposition,
            day_outcome_status: "accepted",
            agent_display_narratives: agentDisplayNarratives,
          });
          if (!scorecardWrite.darwinian_v2) {
            throw new Error("accepted live cycle did not create Darwinian v2 ledgers");
          }
        }
        const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
        if (opts.paperExecuteDeltas) {
          const finalTarget = final.layer4_outputs.runtime?.final_target_state;
          if (!finalTarget) throw new Error("paper execution requires frozen final_target_state");
          const execution = await submitPaperTargetDeltaOrders(api, final.portfolio_actions, {
            analysisId: final.trace_id,
            tradeDate: final.as_of_date,
            runId: finalTarget.run_id,
            finalTargetHash: finalTarget.final_target_hash,
            expectedAccountSnapshotHash: finalTarget.position_snapshot_hash,
          });
          console.log(pc.cyan("\n=== paper execution deltas ==="));
          for (const row of execution) {
            if (!row.suggested_order) {
              console.log(
                (row.skipped_reason === "STALE_FINAL_TARGET" ? pc.red : pc.dim)(
                  `  ${row.ticker} current=${(row.current_weight * 100).toFixed(2)}% ` +
                    `target=${(row.target_weight * 100).toFixed(2)}% ` +
                    `residual=${(row.residual_drift_weight * 100).toFixed(2)}% ` +
                    `${row.skipped_reason ?? "no delta order"}`,
                ),
              );
            } else {
              console.log(
                `  ${row.suggested_order.side} ${row.suggested_order.quantity} ${row.ticker} ` +
                  `current=${(row.current_weight * 100).toFixed(2)}% ` +
                  `target=${(row.target_weight * 100).toFixed(2)}% ` +
                  `delta=${(row.required_delta_weight * 100).toFixed(2)}% ` +
                  `residual=${(row.residual_drift_weight * 100).toFixed(2)}%`,
              );
            }
          }
        }
        if (!nonProductionSmoke) {
          try {
            const capture = await captureDailyCycleRkeFootprints(api, final);
            if (capture) {
              const detail =
                capture.capture_status === "captured"
                  ? `rke_footprints=${capture.captured_count}`
                  : `rke_footprints_blocked=${(capture.failures ?? []).slice(0, 2).join(" | ")}`;
              console.log(pc.dim(redactSensitiveText(detail)));
            }
          } catch (err) {
            console.log(
              pc.dim(redactSensitiveText(`rke_footprints_skipped=${(err as Error).message}`)),
            );
          }
        }

        if (opts.out) {
          // ``state.messages`` are LangChain BaseMessage class instances whose
          // default JSON serialisation surfaces internal fields (lc_kwargs,
          // lc_namespace, ...) that aren't useful downstream. Drop them and
          // surface only the prose content for any consumer that wants it.
          const dump = {
            ...final,
            ...(nonProductionSmoke
              ? {
                  non_production_run_audit: {
                    schema_version: "non_production_run_audit_v1",
                    production_eligible: false,
                    data_source: "HASH_BOUND_BRIDGE_FIXTURE",
                    fixture_bundle_hash: fixtureBundleHash,
                    private_knot_runtime_installed: false,
                  },
                }
              : {}),
            agent_display_narratives: agentDisplayNarratives,
            messages: final.messages.map((m) => ({
              role: m.getType?.() ?? "unknown",
              content: typeof m.content === "string" ? m.content : JSON.stringify(m.content),
            })),
          };
          writeFileSync(opts.out, JSON.stringify(dump, null, 2), "utf-8");
          console.log(pc.dim(`\nstate written to ${opts.out} (${elapsed}s)`));
        } else {
          printCycleSummary(final, elapsed, agentDisplayNarratives);
        }
      } catch (err) {
        if (err instanceof RpcError) {
          console.error(pc.red(`bridge error [${err.code}]: ${redactSensitiveText(err.message)}`));
        } else {
          console.error(pc.red(`error: ${redactSensitiveText((err as Error).message)}`));
        }
        const tail = client?.stderrTail.trim() ?? "";
        if (tail) {
          console.error(pc.dim("\n--- bridge stderr (tail) ---"));
          console.error(pc.dim(redactSensitiveText(tail).slice(-2000)));
        }
        process.exitCode = 1;
      } finally {
        await client?.close();
        restoreOptionalEnv(
          "MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS",
          inheritedRuntimeEnv.sourceGapBypass,
        );
        restoreOptionalEnv(
          "MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH",
          inheritedRuntimeEnv.fixtureBundleHash,
        );
        restoreOptionalEnv("MOSAIC_KNOT_RUNTIME_ROOT", inheritedRuntimeEnv.knotRuntimeRoot);
      }
    });
}

export function assertDailyCyclePromptSourceMode(
  opts: { promptsRoot?: string },
  nonProductionSmoke: boolean,
): void {
  if (!nonProductionSmoke && opts.promptsRoot) {
    throw new Error("live execution forbids --prompts-root; use a pinned --prompts-repo release");
  }
}

export function nonProductionSourceGapBypass(
  opts: Pick<DailyCycleOptions, "fakeLlm" | "structuredSmoke">,
): "structured_smoke" | undefined {
  return opts.fakeLlm || opts.structuredSmoke ? "structured_smoke" : undefined;
}

export function resolveDailyCycleCohort(
  opts: Pick<DailyCycleOptions, "cohort">,
  _config: { active_cohort?: string },
): string {
  // Bridge config still carries the legacy, unprefixed PRISM namespace. It
  // cannot select a formal prompt/KNOT/Darwinian runtime cohort implicitly.
  const cohort = opts.cohort?.trim() || "cohort_default";
  if (!(PRIVATE_KNOT_COHORT_IDS as readonly string[]).includes(cohort)) {
    throw new Error(
      `unknown daily-cycle cohort '${cohort}'; expected one of ${PRIVATE_KNOT_COHORT_IDS.join(", ")}`,
    );
  }
  return cohort;
}

const STRUCTURED_SMOKE_MARKER_FIELDS = [
  "artifact_inventory",
  "artifact_inventory_hash",
  "as_of_date",
  "bundle_hash",
  "cache_root",
  "contains_vendor_prose",
  "fixture_class",
  "geopolitical_manifest",
  "geopolitical_manifest_hash",
  "schema_version",
] as const;
const STRUCTURED_SMOKE_ARTIFACT_ROOTS = [
  "economic_calendar",
  "geopolitical_events",
  "macro_snapshots",
  "market_breadth",
  "runtime_snapshots",
  "sector_snapshots",
] as const;

export function validateStructuredSmokeFixtureBundle(
  asOfDate: string,
  env: NodeJS.ProcessEnv = process.env,
): { bundleHash: string; markerPath: string } {
  const cacheRoot = env.MOSAIC_CACHE_DIR;
  const geopoliticalManifest = env.MOSAIC_GEOPOLITICAL_SOURCE_MANIFEST;
  const expectedBundleHash = env.MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH;
  if (
    !cacheRoot ||
    !geopoliticalManifest ||
    !expectedBundleHash ||
    !/^sha256:[0-9a-f]{64}$/.test(expectedBundleHash)
  ) {
    throw new Error(
      "non-production smoke requires cache, geopolitical manifest, and fixture bundle hash bindings",
    );
  }
  const resolvedRoot = resolve(cacheRoot);
  const markerPath = resolve(resolvedRoot, "structured_smoke_fixture_bundle.json");
  let marker: unknown;
  let manifest: unknown;
  try {
    const markerMetadata = lstatSync(markerPath);
    if (markerMetadata.isSymbolicLink() || !markerMetadata.isFile()) {
      throw new Error("structured-smoke fixture marker must be a regular file");
    }
    marker = JSON.parse(readFileSync(markerPath, "utf-8"));
    manifest = JSON.parse(readFileSync(resolve(geopoliticalManifest), "utf-8"));
  } catch (cause) {
    throw new Error("structured-smoke fixture marker or geopolitical manifest is unavailable", {
      cause,
    });
  }
  if (!isPlainRecord(marker) || !isPlainRecord(manifest)) {
    throw new Error("structured-smoke fixture marker and manifest must be JSON objects");
  }
  if (
    JSON.stringify(Object.keys(marker).sort()) !==
    JSON.stringify([...STRUCTURED_SMOKE_MARKER_FIELDS].sort())
  ) {
    throw new Error("structured-smoke fixture marker fields mismatch");
  }
  const suppliedInventory = validateStructuredSmokeArtifactInventory(marker.artifact_inventory);
  const actualInventory = collectStructuredSmokeArtifactInventory(resolvedRoot);
  if (
    marker.artifact_inventory_hash !== canonicalJsonHash(suppliedInventory) ||
    JSON.stringify(suppliedInventory) !== JSON.stringify(actualInventory)
  ) {
    throw new Error("structured-smoke fixture artifact inventory mismatch");
  }
  const body = Object.fromEntries(Object.entries(marker).filter(([key]) => key !== "bundle_hash"));
  const bundleHash = canonicalJsonHash(body);
  if (
    marker.schema_version !== "structured_smoke_fixture_bundle_v1" ||
    marker.as_of_date !== asOfDate ||
    marker.fixture_class !== "SYNTHETIC_NON_PRODUCTION" ||
    marker.contains_vendor_prose !== false ||
    resolve(String(marker.cache_root)) !== resolvedRoot ||
    resolve(String(marker.geopolitical_manifest)) !== resolve(geopoliticalManifest) ||
    marker.geopolitical_manifest_hash !== manifest.manifest_hash ||
    marker.bundle_hash !== bundleHash ||
    marker.bundle_hash !== expectedBundleHash
  ) {
    throw new Error("structured-smoke fixture marker binding mismatch");
  }
  return { bundleHash, markerPath };
}

function validateStructuredSmokeArtifactInventory(value: unknown): Array<{
  relative_path: string;
  content_sha256: string;
}> {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error("structured-smoke fixture artifact inventory is empty");
  }
  const rows = value.map((item) => {
    if (
      !isPlainRecord(item) ||
      JSON.stringify(Object.keys(item).sort()) !==
        JSON.stringify(["content_sha256", "relative_path"])
    ) {
      throw new Error("structured-smoke fixture artifact inventory row is invalid");
    }
    const relativePath = item.relative_path;
    const contentSha256 = item.content_sha256;
    if (
      typeof relativePath !== "string" ||
      !STRUCTURED_SMOKE_ARTIFACT_ROOTS.some((root) => relativePath.startsWith(`${root}/`)) ||
      relativePath.includes("\\") ||
      relativePath.split("/").some((part) => part === "" || part === "." || part === "..") ||
      typeof contentSha256 !== "string" ||
      !/^sha256:[0-9a-f]{64}$/.test(contentSha256)
    ) {
      throw new Error("structured-smoke fixture artifact inventory row is invalid");
    }
    return { relative_path: relativePath, content_sha256: contentSha256 };
  });
  const sorted = [...rows].sort((left, right) =>
    left.relative_path.localeCompare(right.relative_path),
  );
  if (
    new Set(sorted.map((row) => row.relative_path)).size !== sorted.length ||
    JSON.stringify(rows) !== JSON.stringify(sorted)
  ) {
    throw new Error("structured-smoke fixture artifact inventory must be unique and sorted");
  }
  return rows;
}

function collectStructuredSmokeArtifactInventory(root: string): Array<{
  relative_path: string;
  content_sha256: string;
}> {
  const rows: Array<{ relative_path: string; content_sha256: string }> = [];
  const visit = (path: string): void => {
    const metadata = lstatSync(path);
    if (metadata.isSymbolicLink()) {
      throw new Error("structured-smoke fixture artifact tree contains a symlink");
    }
    if (metadata.isDirectory()) {
      for (const entry of readdirSync(path).sort()) visit(resolve(path, entry));
      return;
    }
    if (!metadata.isFile()) {
      throw new Error("structured-smoke fixture artifact tree contains a non-file entry");
    }
    rows.push({
      relative_path: relative(root, path).split("\\").join("/"),
      content_sha256: `sha256:${createHash("sha256").update(readFileSync(path)).digest("hex")}`,
    });
  };
  try {
    for (const directory of STRUCTURED_SMOKE_ARTIFACT_ROOTS) visit(resolve(root, directory));
  } catch (cause) {
    if (cause instanceof Error && cause.message.startsWith("structured-smoke")) throw cause;
    throw new Error("structured-smoke fixture artifact tree is unavailable", { cause });
  }
  return rows.sort((left, right) => left.relative_path.localeCompare(right.relative_path));
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function canonicalJsonHash(value: unknown): string {
  const canonical = JSON.stringify(sortJsonValue(value));
  return `sha256:${createHash("sha256").update(canonical).digest("hex")}`;
}

function sortJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortJsonValue);
  if (!isPlainRecord(value)) return value;
  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .map((key) => [key, sortJsonValue(value[key])]),
  );
}

function restoreOptionalEnv(name: string, value: string | undefined): void {
  if (value === undefined) delete process.env[name];
  else process.env[name] = value;
}

// ---------------------------------------------------------------------------
// Pretty printer (4 layer summary blocks + portfolio_actions table)
// ---------------------------------------------------------------------------

function printCycleSummary(
  state: DailyCycleStateType,
  elapsed: string,
  agentDisplayNarratives: AgentDisplayNarrativeBundle,
): void {
  console.log(pc.cyan("\n=== Layer 1 — accepted Macro transmissions ==="));
  console.log(
    state.macro_input_gate
      ? pc.dim(`gate=READY hash=${state.macro_input_gate.input_hash}`)
      : pc.red("gate=NOT_READY"),
  );
  for (const output of Object.values(state.layer1_outputs)) {
    console.log(
      `  ${output.agent_id}: ${output.direction} ${output.strength}/5 ` +
        `confidence=${output.confidence.toFixed(2)}`,
    );
  }

  console.log(pc.cyan("\n=== Layer 2 — sector picks ==="));
  const sectors = state.layer2_outputs ?? {};
  if (Object.keys(sectors).length === 0) {
    console.log(pc.dim("(no sector outputs)"));
  }
  for (const [id, out] of Object.entries(sectors)) {
    if (out.agent === "relationship_mapper") {
      console.log(
        `${pc.bold(id)}  ${out.predictive_graph_status}  ` +
          `factual=${out.factual_edges.length} predictive=${out.predictive_edges.length}`,
      );
    } else {
      const longs = out.long_picks
        .slice(0, 3)
        .map((p) => `${p.ts_code}(${p.conviction.toFixed(2)})`)
        .join(", ");
      console.log(
        `${pc.bold(id)}  preferred=${out.preferred_direction.direction_id}  ` +
          `least=${out.least_preferred_direction.direction_id}  ` +
          `conf=${out.confidence.toFixed(2)}  longs: ${longs || "(none)"}`,
      );
    }
  }

  console.log(pc.cyan("\n=== Layer 3 — superinvestor picks ==="));
  const supers = state.layer3_outputs ?? {};
  if (Object.keys(supers).length === 0) {
    console.log(pc.dim("(no superinvestor outputs)"));
  }
  for (const [id, out] of Object.entries(supers)) {
    const picks = out.picks
      .slice(0, 4)
      .map((p) => `${p.ts_code}(${out.holding_period},${p.conviction.toFixed(2)})`)
      .join(", ");
    console.log(`${pc.bold(id)}  conf=${out.confidence.toFixed(2)}  ${picks || "(no picks)"}`);
  }

  console.log(pc.cyan("\n=== Layer 4 — decision ==="));
  const l4 = state.layer4_outputs;
  if (l4.cro) {
    console.log(
      `${pc.bold("cro")}  conf=${l4.cro.confidence.toFixed(2)}  rejected=${l4.cro.rejected_picks.length}` +
        (l4.cro.black_swan_scenarios.length > 0
          ? `  black_swan=${l4.cro.black_swan_scenarios.length}`
          : ""),
    );
  }
  if (l4.alpha_discovery) {
    console.log(
      `${pc.bold("alpha_discovery")}  conf=${l4.alpha_discovery.confidence.toFixed(2)}  novel=${l4.alpha_discovery.novel_picks.length}`,
    );
  }
  if (l4.autonomous_execution) {
    console.log(
      `${pc.bold("autonomous_execution")}  conf=${l4.autonomous_execution.confidence.toFixed(2)}  trades=${l4.autonomous_execution.trades.length}`,
    );
  }
  if (l4.cio) {
    console.log(
      `${pc.bold("cio")}  conf=${l4.cio.confidence.toFixed(2)}  actions=${l4.cio.portfolio_actions.length}`,
    );
  }

  console.log(pc.cyan("\n=== portfolio_actions (final) ==="));
  printPositionAudit(state);
  printPortfolioTable(state.portfolio_actions, state.layer4_outputs.cio?.decision_disposition);

  console.log(pc.cyan("\n=== Agent decision narratives (UI-only) ==="));
  for (const narrative of agentDisplayNarratives.narratives) {
    console.log(pc.bold(`\n[${narrative.agent_id}] ${narrative.layer}`));
    for (const line of narrative.narrative_text.split("\n")) {
      console.log(`  ${line}`);
    }
  }

  console.log(pc.dim(`\ntotal=${state.llm_calls.length} llm calls, elapsed=${elapsed}s`));
}

function printPositionAudit(state: DailyCycleStateType): void {
  const audit = state.position_audit;
  console.log(
    pc.dim(
      `positions=${audit.snapshot_status}/${audit.position_source} loaded=${audit.positions_loaded} ` +
        `reviewed=${audit.positions_reviewed} unreviewed=${audit.positions_unreviewed}`,
    ),
  );
  const warnings: string[] = [];
  if (audit.positions_unreviewed > 0) warnings.push("UNREVIEWED_POSITION");
  if (audit.snapshot_status === "missing") warnings.push("MISSING_POSITION_SNAPSHOT");
  if (audit.stale_thesis_count > 0) warnings.push("STALE_THESIS");
  if (audit.stop_loss_override_count > 0) warnings.push("STOP_LOSS_OVERRIDE");
  if (audit.target_current_drift_count > 0) warnings.push("TARGET_CURRENT_DRIFT");
  if (warnings.length > 0) {
    console.log(pc.yellow(`  warnings=${warnings.join(",")}`));
  }
}

function printPortfolioTable(
  actions: PortfolioAction[],
  decisionDisposition?: "TARGET_PORTFOLIO" | "HOLD_CURRENT" | "ALL_CASH",
): void {
  if (actions.length === 0) {
    console.log(
      decisionDisposition === "ALL_CASH"
        ? pc.dim("(accepted ALL_CASH — holding 100% cash)")
        : pc.red("(FAILED_NO_DECISION — empty portfolio actions without accepted ALL_CASH)"),
    );
    return;
  }
  const totalWeight = actions.reduce((s, a) => s + a.target_weight, 0);
  console.log(
    `  ${pad("ticker", 12)} ${pad("action", 7)} ${pad("pos", 7)} ${pad("cur", 7)} ` +
      `${pad("target", 7)} ${pad("delta", 7)} ${pad("thesis", 8)} dissent`,
  );
  for (const a of actions) {
    console.log(
      `  ${pad(a.ticker, 12)} ${pad(a.action, 7)} ${pad(a.position_decision ?? "-", 7)} ` +
        `${pad(formatWeight(a.current_weight), 7)} ${pad(a.target_weight.toFixed(2), 7)} ` +
        `${pad(formatWeight(a.delta_weight), 7)} ${pad(a.thesis_status ?? "-", 8)} ` +
        `${a.dissent_notes || ""}`,
    );
  }
  console.log(pc.dim(`  total_weight = ${totalWeight.toFixed(2)}`));
}

function formatWeight(value: number | undefined): string {
  return value === undefined ? "-" : value.toFixed(2);
}

// pad() imported from ../_format.js (§14 R-T2: shared CJK + ANSI-aware).

export async function loadDailyCycleCurrentPositions(
  opts: Pick<DailyCycleOptions, "paperPositions" | "currentPositionsJson" | "currentPositionsFile">,
  api: BridgeApi,
): Promise<CurrentPositionsSnapshot> {
  if (opts.paperPositions && (opts.currentPositionsJson || opts.currentPositionsFile)) {
    throw new Error("choose either --paper-positions or a current-position fixture, not both");
  }
  const fixture = loadCurrentPositionsFixture(opts);
  if (fixture) return fixture;
  return opts.paperPositions ? await loadPaperCurrentPositions(api) : emptyCurrentPositions();
}

export function loadCurrentPositionsFixture(
  opts: Pick<DailyCycleOptions, "currentPositionsJson" | "currentPositionsFile">,
): CurrentPositionsSnapshot | null {
  if (opts.currentPositionsJson && opts.currentPositionsFile) {
    throw new Error("choose only one current-position fixture source");
  }
  let raw: unknown = null;
  if (opts.currentPositionsFile) {
    raw = JSON.parse(readFileSync(opts.currentPositionsFile, "utf-8")) as unknown;
  }
  if (opts.currentPositionsJson) {
    raw = JSON.parse(opts.currentPositionsJson) as unknown;
  }
  if (raw === null) return null;
  const snapshot = normalizeCurrentPositionsFixture(raw);
  return {
    ...snapshot,
    position_snapshot_hash:
      snapshot.position_snapshot_hash ?? currentPositionFixtureHash(snapshot.positions),
  };
}

async function loadPaperCurrentPositions(api: BridgeApi): Promise<CurrentPositionsSnapshot> {
  try {
    const {
      account,
      positions,
      snapshot_hash: snapshotHash,
    } = await api.paperGetPortfolioSnapshot();
    if (positions.length === 0) {
      return {
        ...emptyCurrentPositions(),
        position_source: "paper_account",
        position_snapshot_hash: snapshotHash,
      };
    }
    const totalAssets =
      account.total_assets > 0
        ? account.total_assets
        : positions.reduce((sum, position) => sum + position.market_value, 0);
    return {
      snapshot_status: "loaded",
      position_source: "paper_account",
      source_error_code: null,
      position_snapshot_hash: snapshotHash,
      positions: positions.map((position) => ({
        ticker: position.ticker,
        current_weight: totalAssets > 0 ? position.market_value / totalAssets : 0,
        cost_basis: position.avg_cost,
        market_price: position.current_price,
        unrealized_pnl_pct: position.pnl_pct / 100,
        holding_days: 0,
        entry_date: position.updated_at.slice(0, 10),
        source_agent: "paper_account",
        entry_thesis_id: `paper:${position.ticker}`,
        last_review_date: position.updated_at.slice(0, 10),
      })),
    };
  } catch (err) {
    return {
      snapshot_status: "missing",
      position_source: "paper_account",
      source_error_code: `paper_positions_unavailable:${(err as Error).message.slice(0, 80)}`,
      position_snapshot_hash: undefined,
      positions: [],
    };
  }
}

function currentPositionFixtureHash(positions: ReadonlyArray<CurrentPosition>): string {
  const payload = JSON.stringify(positions);
  return `sha256:${createHash("sha256").update(payload).digest("hex")}`;
}

function normalizeCurrentPositionsFixture(raw: unknown): CurrentPositionsSnapshot {
  if (Array.isArray(raw)) {
    return snapshotFromFixturePositions(raw);
  }
  if (raw === null || typeof raw !== "object") {
    throw new Error("current positions fixture must be a JSON array or object");
  }
  const record = raw as Record<string, unknown>;
  const positionsValue = record.current_positions ?? record.positions;
  if (!Array.isArray(positionsValue)) {
    throw new Error("current positions fixture must contain current_positions or positions array");
  }
  const snapshot = snapshotFromFixturePositions(positionsValue);
  const status = optionalString(record.snapshot_status);
  if (status !== null) {
    if (!["loaded", "empty_confirmed", "missing"].includes(status)) {
      throw new Error(`snapshot_status must be loaded, empty_confirmed, or missing: ${status}`);
    }
    snapshot.snapshot_status = status as CurrentPositionsSnapshot["snapshot_status"];
  }
  snapshot.source_error_code = optionalString(record.source_error_code);
  snapshot.position_snapshot_hash = optionalString(record.position_snapshot_hash) ?? undefined;
  return snapshot;
}

function snapshotFromFixturePositions(values: unknown[]): CurrentPositionsSnapshot {
  const positions = values.map((value, index) => normalizeFixturePosition(value, index));
  return {
    snapshot_status: positions.length > 0 ? "loaded" : "empty_confirmed",
    position_source: positions.length > 0 ? "cli_fixture" : "empty_confirmed",
    source_error_code: null,
    positions,
  };
}

function normalizeFixturePosition(value: unknown, index: number): CurrentPosition {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`current_positions[${index}] must be an object`);
  }
  const record = value as Record<string, unknown>;
  const ticker = requiredString(record.ticker, `current_positions[${index}].ticker`);
  const sector = optionalString(record.sector);
  return {
    ticker,
    ...(sector ? { sector } : {}),
    current_weight: requiredFiniteNumber(
      record.current_weight,
      `current_positions[${index}].current_weight`,
    ),
    cost_basis: requiredFiniteNumber(record.cost_basis, `current_positions[${index}].cost_basis`),
    market_price: requiredFiniteNumber(
      record.market_price,
      `current_positions[${index}].market_price`,
    ),
    unrealized_pnl_pct: requiredFiniteNumber(
      record.unrealized_pnl_pct,
      `current_positions[${index}].unrealized_pnl_pct`,
    ),
    holding_days: requiredFiniteNumber(
      record.holding_days,
      `current_positions[${index}].holding_days`,
    ),
    entry_date: requiredString(record.entry_date, `current_positions[${index}].entry_date`),
    source_agent: requiredString(record.source_agent, `current_positions[${index}].source_agent`),
    entry_thesis_id: requiredString(
      record.entry_thesis_id,
      `current_positions[${index}].entry_thesis_id`,
    ),
    last_review_date: requiredString(
      record.last_review_date,
      `current_positions[${index}].last_review_date`,
    ),
  };
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function requiredFiniteNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label} must be a finite number`);
  }
  return value;
}

function positionAuditFromSnapshot(snapshot: CurrentPositionsSnapshot): PositionAudit {
  return {
    position_snapshot_hash: snapshot.position_snapshot_hash ?? null,
    snapshot_status: snapshot.snapshot_status,
    position_source: snapshot.position_source,
    source_error_code: snapshot.source_error_code,
    tool_status_summary: buildPositionAuditToolStatusSummary(snapshot),
    positions_loaded: snapshot.positions.length,
    positions_reviewed: 0,
    positions_unreviewed: snapshot.positions.length,
    hold_count: 0,
    add_count: 0,
    reduce_count: 0,
    exit_count: 0,
    stale_thesis_count: 0,
    stop_loss_override_count: 0,
    target_current_drift_count: 0,
  };
}

export async function submitPaperTargetDeltaOrders(
  api: Pick<BridgeApi, "paperSuggestOrderFromSignal" | "paperBuy" | "paperSell"> &
    Partial<Pick<BridgeApi, "paperGetPortfolioSnapshot">>,
  actions: ReadonlyArray<PortfolioAction>,
  opts: {
    userId?: string;
    dbPath?: string;
    analysisId?: string;
    tradeDate?: string;
    runId?: string;
    finalTargetHash?: string;
    expectedAccountSnapshotHash?: string | null;
  } = {},
): Promise<PaperDeltaExecution[]> {
  const results: PaperDeltaExecution[] = [];
  const skippedRow = (
    action: PortfolioAction,
    reason: string,
    extra: Partial<PaperDeltaExecution> = {},
  ): PaperDeltaExecution => {
    const currentWeight =
      action.current_weight ?? action.target_weight - (action.delta_weight ?? 0);
    const requiredDelta = action.target_weight - currentWeight;
    return {
      ticker: action.ticker,
      current_weight: currentWeight,
      target_weight: action.target_weight,
      required_delta_weight: requiredDelta,
      residual_drift_weight: requiredDelta,
      order_intent_key: null,
      suggested_order: null,
      submitted_order: null,
      ...(opts.finalTargetHash ? { final_target_hash: opts.finalTargetHash } : {}),
      ...(opts.expectedAccountSnapshotHash
        ? { final_target_position_snapshot_hash: opts.expectedAccountSnapshotHash }
        : {}),
      skipped_reason: reason,
      ...extra,
    };
  };
  let accountSnapshotHash = opts.expectedAccountSnapshotHash ?? null;
  if (opts.finalTargetHash) {
    if (
      !opts.runId ||
      !accountSnapshotHash ||
      typeof api.paperGetPortfolioSnapshot !== "function"
    ) {
      return actions.map((action) => skippedRow(action, "STALE_FINAL_TARGET"));
    }
    const finalTargetPositionSnapshotHash = accountSnapshotHash;
    let current: Awaited<ReturnType<NonNullable<typeof api.paperGetPortfolioSnapshot>>>;
    try {
      current = await api.paperGetPortfolioSnapshot({
        ...(opts.userId ? { user_id: opts.userId } : {}),
        ...(opts.dbPath ? { db_path: opts.dbPath } : {}),
      });
    } catch {
      return actions.map((action) => skippedRow(action, "STALE_FINAL_TARGET"));
    }
    if (current.snapshot_hash !== finalTargetPositionSnapshotHash) {
      return actions.map((action) =>
        skippedRow(action, "STALE_FINAL_TARGET", {
          base_account_snapshot_hash: finalTargetPositionSnapshotHash,
          post_submit_snapshot_hash: current.snapshot_hash,
        }),
      );
    }
  }
  for (let actionIndex = 0; actionIndex < actions.length; actionIndex += 1) {
    const action = actions[actionIndex];
    if (!action) continue;
    const currentWeight =
      action.current_weight ?? action.target_weight - (action.delta_weight ?? 0);
    const requiredDelta = action.target_weight - currentWeight;
    const targetWeightPct = action.target_weight * 100;
    const signalState = {
      backtest_signal: {
        ticker: action.ticker,
        decision_date: opts.tradeDate ?? new Date().toISOString().slice(0, 10),
        source: "daily_cycle_position_target",
        source_section: "portfolio_actions",
        rating: action.action,
        target_weight_pct: targetWeightPct,
        target_weight_min_pct: targetWeightPct,
        target_weight_max_pct: targetWeightPct,
        weight_source: "target_portfolio_weight",
      },
    };
    let suggested: PaperSuggestion | null;
    try {
      suggested = await api.paperSuggestOrderFromSignal({
        ticker: action.ticker,
        state: signalState,
        ...(opts.userId ? { user_id: opts.userId } : {}),
        ...(opts.dbPath ? { db_path: opts.dbPath } : {}),
      });
    } catch {
      results.push(skippedRow(action, "ORDER_PLANNING_FAILED"));
      continue;
    }
    if (!suggested) {
      results.push(skippedRow(action, "already_at_target_or_below_lot_size"));
      continue;
    }
    const orderIntentKey =
      opts.runId && opts.finalTargetHash
        ? sha256Json({
            run_id: opts.runId,
            final_target_hash: opts.finalTargetHash,
            ticker: action.ticker,
            side: suggested.side,
          })
        : null;
    const orderAccountSnapshotHash = accountSnapshotHash;
    const orderParams = {
      ticker: suggested.ticker,
      quantity: suggested.quantity,
      ...(opts.userId ? { user_id: opts.userId } : {}),
      ...(opts.analysisId ? { analysis_id: opts.analysisId } : {}),
      ...(opts.dbPath ? { db_path: opts.dbPath } : {}),
      ...(orderIntentKey ? { order_intent_key: orderIntentKey } : {}),
      ...(accountSnapshotHash ? { expected_account_snapshot_hash: accountSnapshotHash } : {}),
      ...(opts.finalTargetHash ? { final_target_hash: opts.finalTargetHash } : {}),
    };
    let submitted: PaperOrderResult;
    try {
      submitted =
        suggested.side === "buy"
          ? await api.paperBuy(orderParams)
          : await api.paperSell(orderParams);
    } catch (error) {
      const stale = (error as Error).message.includes("STALE_FINAL_TARGET");
      results.push({
        ticker: action.ticker,
        current_weight: currentWeight,
        target_weight: action.target_weight,
        required_delta_weight: requiredDelta,
        residual_drift_weight: requiredDelta,
        order_intent_key: orderIntentKey,
        suggested_order: suggested,
        submitted_order: null,
        ...(opts.finalTargetHash ? { final_target_hash: opts.finalTargetHash } : {}),
        ...(opts.expectedAccountSnapshotHash
          ? { final_target_position_snapshot_hash: opts.expectedAccountSnapshotHash }
          : {}),
        ...(orderAccountSnapshotHash
          ? { base_account_snapshot_hash: orderAccountSnapshotHash }
          : {}),
        skipped_reason: stale ? "STALE_FINAL_TARGET" : "ORDER_REJECTED",
      });
      if (stale) {
        results.push(
          ...actions
            .slice(actionIndex + 1)
            .map((remaining) => skippedRow(remaining, "STALE_FINAL_TARGET")),
        );
        break;
      }
      continue;
    }

    const filledRatio =
      submitted.fill_status === "rejected"
        ? 0
        : submitted.quantity > 0 && submitted.filled_quantity !== undefined
          ? Math.min(1, Math.max(0, submitted.filled_quantity / submitted.quantity))
          : 1;
    let residualDriftWeight = requiredDelta * (1 - filledRatio);
    let postSubmitSnapshotHash: string | undefined;
    if (opts.finalTargetHash && typeof api.paperGetPortfolioSnapshot === "function") {
      try {
        const postSubmit = await api.paperGetPortfolioSnapshot({
          ...(opts.userId ? { user_id: opts.userId } : {}),
          ...(opts.dbPath ? { db_path: opts.dbPath } : {}),
        });
        accountSnapshotHash = postSubmit.snapshot_hash;
        postSubmitSnapshotHash = postSubmit.snapshot_hash;
        const position = postSubmit.positions.find((item) => item.ticker === action.ticker);
        const actualWeight =
          position && postSubmit.account.total_assets > 0
            ? position.market_value / postSubmit.account.total_assets
            : 0;
        residualDriftWeight = action.target_weight - actualWeight;
      } catch {
        results.push({
          ...skippedRow(action, "POST_SUBMIT_SNAPSHOT_UNAVAILABLE"),
          order_intent_key: orderIntentKey,
          suggested_order: suggested,
          submitted_order: submitted,
          residual_drift_weight: residualDriftWeight,
          ...(orderAccountSnapshotHash
            ? { base_account_snapshot_hash: orderAccountSnapshotHash }
            : {}),
        });
        results.push(
          ...actions
            .slice(actionIndex + 1)
            .map((remaining) => skippedRow(remaining, "POST_SUBMIT_SNAPSHOT_UNAVAILABLE")),
        );
        break;
      }
    }
    results.push({
      ticker: action.ticker,
      current_weight: currentWeight,
      target_weight: action.target_weight,
      required_delta_weight: requiredDelta,
      residual_drift_weight: residualDriftWeight,
      order_intent_key: orderIntentKey,
      suggested_order: suggested,
      submitted_order: submitted,
      ...(opts.finalTargetHash ? { final_target_hash: opts.finalTargetHash } : {}),
      ...(opts.expectedAccountSnapshotHash
        ? { final_target_position_snapshot_hash: opts.expectedAccountSnapshotHash }
        : {}),
      ...(orderAccountSnapshotHash ? { base_account_snapshot_hash: orderAccountSnapshotHash } : {}),
      ...(postSubmitSnapshotHash ? { post_submit_snapshot_hash: postSubmitSnapshotHash } : {}),
    });
  }
  return results;
}

function sha256Json(value: unknown): string {
  return `sha256:${createHash("sha256").update(JSON.stringify(value)).digest("hex")}`;
}

// ---------------------------------------------------------------------------
// Fake LLM for --fake-llm mode
// ---------------------------------------------------------------------------

/** Schema-driven fake used only to validate the complete strict-contract wiring. */
class FakeChatModel {
  private tools: Array<{ name: string; schema?: unknown }> = [];

  bindTools(tools: unknown): FakeChatModel {
    this.tools = Array.isArray(tools) ? tools : [];
    return this;
  }
  withStructuredOutput(
    schema: unknown,
    options?: { name?: string },
  ): { invoke: (messages: unknown) => Promise<unknown> } {
    return {
      invoke: async (messages) => ({
        raw: new AIMessage("(--fake-llm) deterministic structured smoke output."),
        parsed: fakeAgentStructuredOutput(schema, options?.name ?? "fake_agent", messages),
      }),
    };
  }
  async invoke(messages: BaseMessage[]): Promise<AIMessage> {
    if (this.tools.length > 0 && !messages.some((message) => message._getType() === "tool")) {
      return new AIMessage({
        content: "",
        tool_calls: this.tools.map((tool, index) => ({
          id: `fake-tool-${index}`,
          name: tool.name,
          args: fakeSchemaValue(tool.schema),
        })),
      });
    }
    return new AIMessage("(--fake-llm) deterministic analysis for strict structured smoke output.");
  }
}

function buildFakeLlmHandle(): LlmHandle {
  return {
    llm: new FakeChatModel() as unknown as BaseChatModel,
    provider: "fake",
    model: "fake-llm-mock",
    baseUrl: undefined,
  };
}
