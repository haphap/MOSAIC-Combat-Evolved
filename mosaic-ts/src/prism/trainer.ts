/**
 * PRISM training orchestration (Plan §11.6 Phase 5 / §1 concurrency model).
 *
 * Scales the Phase 4 single-agent autoresearch cycle up to multi-cohort
 * training, under the §1 concurrency contract:
 *   - cohorts are trained SEQUENTIALLY (avoid 7×25 concurrent LLM calls);
 *   - within a cohort, layers run SEQUENTIALLY (macro → sector →
 *     superinvestor → decision — lower layers consume upper-layer output);
 *   - within a layer, up to ``maxAgentsConcurrent`` (default 5) agents train
 *     concurrently.
 *
 * Each (cohort, agent) training step is just one ``runAutoresearchCycle`` with
 * ``forceAgent`` — Phase 5 is a pure orchestration layer and does not
 * reimplement trigger/mutate/evaluate/decide.
 */

import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import { AGENTS_BY_LAYER, type Layer } from "../agents/prompts/cohorts.js";
import {
  type AutoresearchCycleOptions,
  type MutationResult,
  runAutoresearchCycle,
} from "../autoresearch/orchestrator.js";
import type { BridgeApi } from "../bridge/types.js";

/** Layer training order (Plan §1: lower layers depend on upper-layer output). */
export const LAYER_ORDER: ReadonlyArray<Layer> = ["macro", "sector", "superinvestor", "decision"];

export interface CohortTrainingOptions {
  cohort: string;
  /** Restrict to a subset of layers (default: all four, in LAYER_ORDER). */
  layers?: ReadonlyArray<Layer>;
  /** Max agents trained concurrently within one layer (Plan §1, default 5). */
  maxAgentsConcurrent?: number;
  /** Mutations attempted per agent per training pass (default 1). */
  maxMutationsPerAgent?: number;
  dryRun?: boolean;
  fakeLlm?: boolean;
  deps: { llm: BaseChatModel; api: BridgeApi };
  onLog?: (msg: string) => void;
}

export interface LayerTrainingResult {
  layer: Layer;
  agents: MutationResult[];
}

export interface CohortTrainingResult {
  cohort: string;
  layers: LayerTrainingResult[];
}

/**
 * Run ``fn`` over ``items`` with at most ``limit`` in flight at once,
 * preserving input order in the returned results. No external dependency.
 */
async function pool<T, R>(
  items: ReadonlyArray<T>,
  limit: number,
  fn: (item: T) => Promise<R>,
): Promise<R[]> {
  const results = new Array<R>(items.length);
  let next = 0;
  const worker = async (): Promise<void> => {
    while (true) {
      const i = next++;
      if (i >= items.length) return;
      results[i] = await fn(items[i] as T);
    }
  };
  const workers = Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, worker);
  await Promise.all(workers);
  return results;
}

/**
 * Train every agent of one cohort: layers sequential, agents within a layer
 * concurrent up to ``maxAgentsConcurrent``.
 */
export async function runCohortTraining(
  opts: CohortTrainingOptions,
): Promise<CohortTrainingResult> {
  const {
    cohort,
    layers = LAYER_ORDER,
    maxAgentsConcurrent = 5,
    maxMutationsPerAgent = 1,
    dryRun = false,
    fakeLlm = false,
    deps,
    onLog,
  } = opts;
  const log = onLog ?? (() => {});

  const layerResults: LayerTrainingResult[] = [];

  for (const layer of layers) {
    const agents = AGENTS_BY_LAYER[layer] ?? [];
    log(
      `cohort=${cohort} layer=${layer} (${agents.length} agents, ≤${maxAgentsConcurrent} concurrent)`,
    );

    const agentResults = await pool(agents, maxAgentsConcurrent, async (agent) => {
      const cycleOpts: AutoresearchCycleOptions = {
        cohort,
        forceAgent: agent,
        maxMutations: maxMutationsPerAgent,
        dryRun,
        ...(fakeLlm ? { fakeLlm: true } : {}),
        deps,
        onLog: (m) => log(`  [${layer}/${agent}] ${m}`),
      };
      const { mutations } = await runAutoresearchCycle(cycleOpts);
      // One agent + maxMutations=1 → one MutationResult; synthesize a skipped
      // entry when the agent produced nothing (e.g. all on cooldown).
      return (
        mutations[0] ?? {
          agent,
          version_id: null,
          status: "needs_fill" as const,
          summary: "no mutation produced",
        }
      );
    });

    layerResults.push({ layer, agents: agentResults });
  }

  return { cohort, layers: layerResults };
}

export interface PrismTrainingOptions extends Omit<CohortTrainingOptions, "cohort"> {
  /** Cohorts to train, in order (sequential). */
  cohorts: ReadonlyArray<string>;
}

/**
 * Train multiple cohorts SEQUENTIALLY (Plan §1: cohorts never run
 * concurrently to avoid saturating the LLM provider).
 */
export async function runPrismTraining(
  opts: PrismTrainingOptions,
): Promise<CohortTrainingResult[]> {
  const { cohorts, ...rest } = opts;
  const out: CohortTrainingResult[] = [];
  for (const cohort of cohorts) {
    out.push(await runCohortTraining({ cohort, ...rest }));
  }
  return out;
}
