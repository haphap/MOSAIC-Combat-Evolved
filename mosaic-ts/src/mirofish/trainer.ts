/**
 * MiroFish forward-training orchestrator (Plan §11.8 Phase 7).
 *
 * Drives the synthetic-futures training loop:
 *   1. ask Python for the Monte-Carlo scenario set (mirofish.generate_scenarios);
 *   2. present each scenario to each agent → an LLM recommendation
 *      (BUY/SELL/HOLD + tickers + conviction);
 *   3. score the recommendation against the scenario path (Python);
 *   4. record the per-agent average score to the isolated mirofish_runs ledger.
 *
 * Python owns scenario generation + scoring + persistence; this file owns the
 * LLM agent-recommendation step. ``--fake-llm`` swaps in a deterministic canned
 * recommendation so the smoke + tests are reproducible and zero-cost.
 *
 * This is *imagination-mode* training — results never touch real P&L / scorecard
 * alpha (Plan §11.8 isolation principle).
 */

import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import { z } from "zod";
import { bindStructured } from "../agents/helpers/structured_output.js";
import type { BridgeApi, MirofishRecommendation, MirofishScenario } from "../bridge/types.js";

export const RecommendationSchema = z.object({
  recommendation: z.enum(["BUY", "SELL", "HOLD"]),
  tickers: z.array(z.string()),
  conviction: z.number().min(0).max(1),
  reasoning: z.string(),
});

export interface MirofishTrainingOptions {
  numDays?: number;
  seed?: number;
  scenarios?: string[];
  agents: string[];
  dryRun?: boolean;
  fakeLlm?: boolean;
  date?: string;
  deps: { llm: BaseChatModel; api: BridgeApi };
  onLog?: (msg: string) => void;
}

export interface AgentTrainingResult {
  agent: string;
  avg_score: number;
  scenario_scores: Array<{
    scenario_type: string;
    score: number;
    recommendation: MirofishRecommendation;
  }>;
}

export interface MirofishTrainingResult {
  date: string;
  n_scenarios: number;
  agents: AgentTrainingResult[];
}

const META = [
  "You are an A-share portfolio analyst. Given a simulated 30-day market",
  "scenario (price paths + events), give ONE trading recommendation.",
  "Pick from the scenario's tickers. conviction is 0..1. Be decisive.",
].join("\n");

/** Deterministic canned rec for --fake-llm: long the strongest path. */
function cannedRecommendation(scenario: MirofishScenario): MirofishRecommendation {
  let best = "";
  let bestRet = Number.NEGATIVE_INFINITY;
  for (const [ticker, p] of Object.entries(scenario.price_paths)) {
    if (p.cumulative_return > bestRet) {
      bestRet = p.cumulative_return;
      best = ticker;
    }
  }
  return {
    recommendation: bestRet >= 0 ? "BUY" : "SELL",
    tickers: best ? [best] : [],
    conviction: 0.6,
    reasoning: "fake-llm: follow the strongest simulated path",
  };
}

async function agentRecommendation(
  llm: BaseChatModel,
  agent: string,
  scenario: MirofishScenario,
  fakeLlm: boolean,
): Promise<MirofishRecommendation> {
  if (fakeLlm) return cannedRecommendation(scenario);

  const bound = bindStructured(llm, RecommendationSchema, `mirofish:${agent}`);
  if (bound === null) throw new Error(`mirofish:${agent}: provider lacks structured output`);
  const paths = Object.entries(scenario.price_paths)
    .map(
      ([t, p]) =>
        `  ${t}: ${(p.cumulative_return * 100).toFixed(1)}% (vol ${(p.volatility * 100).toFixed(0)}%)`,
    )
    .join("\n");
  const events = scenario.events.map((e) => `  day ${e.day}: ${e.event} [${e.impact}]`).join("\n");
  const user = [
    `Agent: ${agent}`,
    `Scenario: ${scenario.scenario_name} (p=${scenario.probability})`,
    `Price paths (30d):\n${paths}`,
    `Events:\n${events}`,
  ].join("\n\n");
  return RecommendationSchema.parse(
    await bound.invoke([new SystemMessage(META), new HumanMessage(user)]),
  );
}

/**
 * Run one forward-training cycle over all scenarios × agents. In ``dryRun`` the
 * per-agent results are computed but not persisted to the ledger.
 */
export async function runMirofishTraining(
  opts: MirofishTrainingOptions,
): Promise<MirofishTrainingResult> {
  const {
    numDays = 30,
    seed,
    scenarios,
    agents,
    dryRun = false,
    fakeLlm = false,
    date,
    deps,
    onLog,
  } = opts;
  const log = onLog ?? (() => {});

  const { scenarios: scenes } = await deps.api.mirofishGenerateScenarios({
    num_days: numDays,
    ...(seed != null ? { seed } : {}),
    ...(scenarios ? { scenarios } : {}),
  });
  log(`generated ${scenes.length} scenarios (${numDays}d)`);

  const results: AgentTrainingResult[] = [];
  for (const agent of agents) {
    const scenarioScores: AgentTrainingResult["scenario_scores"] = [];
    for (const scenario of scenes) {
      let rec: MirofishRecommendation;
      try {
        rec = await agentRecommendation(deps.llm, agent, scenario, fakeLlm);
      } catch (err) {
        log(`[${agent}/${scenario.scenario_type}] rec failed: ${(err as Error).message}`);
        continue;
      }
      const { score } = await deps.api.mirofishScoreRecommendation({
        recommendation: rec,
        scenario,
      });
      scenarioScores.push({ scenario_type: scenario.scenario_type, score, recommendation: rec });
    }
    const avg =
      scenarioScores.length > 0
        ? scenarioScores.reduce((s, x) => s + x.score, 0) / scenarioScores.length
        : 0;
    log(`[${agent}] avg_score=${avg.toFixed(3)} over ${scenarioScores.length} scenarios`);

    if (!dryRun) {
      await deps.api.mirofishRecordRun({
        agent,
        scenario_type: scenarios && scenarios.length === 1 ? (scenarios[0] as string) : "all",
        n_scenarios: scenarioScores.length,
        avg_score: avg,
        ...(date ? { date } : {}),
        detail: scenarioScores.map((s) => ({ scenario: s.scenario_type, score: s.score })),
      });
    }
    results.push({ agent, avg_score: avg, scenario_scores: scenarioScores });
  }

  return {
    date: date ?? new Date().toISOString().slice(0, 10),
    n_scenarios: scenes.length,
    agents: results,
  };
}
