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
import { extractTextContent } from "../agents/helpers/content.js";
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
  reflexive?: boolean;
  engine?: "montecarlo" | "swarm" | "oasis";
  scorer?: "terminal" | "path_aware";
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

const JSON_META = [
  META,
  "",
  "Return ONLY one valid JSON object. No Markdown, no code fence, no prose before or after it.",
  'Schema: {"recommendation":"BUY|SELL|HOLD","tickers":["000300.SH"],"conviction":0.0,"reasoning":"short rationale"}',
  "Use uppercase English for recommendation. tickers must be selected from the scenario tickers.",
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
  const response = await llm.invoke([new SystemMessage(JSON_META), new HumanMessage(user)]);
  const content =
    typeof response.content === "string" ? response.content : extractTextContent(response.content);
  return parseRecommendationResponse(content, scenario);
}

export function parseRecommendationResponse(
  responseText: string,
  scenario: MirofishScenario,
): MirofishRecommendation {
  const parsed = parseJsonObject(responseText);
  return RecommendationSchema.parse(normalizeRecommendationPayload(parsed, scenario));
}

function parseJsonObject(text: string): unknown {
  const trimmed = text.trim();
  if (!trimmed) throw new Error("empty recommendation response");

  try {
    return JSON.parse(trimmed);
  } catch {
    // Continue to extract the first balanced JSON object from responses that
    // include code fences or explanatory prose despite the JSON-only prompt.
  }

  const fence = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence?.[1]) {
    try {
      return JSON.parse(fence[1].trim());
    } catch {
      // Fall through to the balanced-object extractor.
    }
  }

  const objectText = firstBalancedJsonObject(trimmed);
  if (!objectText) {
    throw new Error(
      `recommendation response did not contain a JSON object: ${trimmed.slice(0, 160)}`,
    );
  }
  return JSON.parse(objectText);
}

function firstBalancedJsonObject(text: string): string | null {
  const start = text.indexOf("{");
  if (start < 0) return null;

  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = start; i < text.length; i++) {
    const ch = text[i];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (ch === "\\") {
      escaped = true;
      continue;
    }
    if (ch === '"') {
      inString = !inString;
      continue;
    }
    if (inString) continue;
    if (ch === "{") depth++;
    if (ch === "}") {
      depth--;
      if (depth === 0) return text.slice(start, i + 1);
    }
  }
  return null;
}

function normalizeRecommendationPayload(
  payload: unknown,
  scenario: MirofishScenario,
): MirofishRecommendation {
  if (!isRecord(payload)) throw new Error("recommendation JSON must be an object");

  const recommendation = normalizeAction(
    pickString(payload, ["recommendation", "action", "decision", "signal", "建议", "操作"]),
  );
  const tickers = normalizeTickers(
    pickValue(payload, [
      "tickers",
      "ticker",
      "symbols",
      "symbol",
      "targets",
      "target",
      "标的",
      "代码",
    ]),
    scenario,
  );
  const conviction = normalizeConviction(
    pickValue(payload, ["conviction", "confidence", "score", "置信度", "信心"]),
  );
  const reasoning =
    pickString(payload, [
      "reasoning",
      "rationale",
      "reason",
      "analysis",
      "thesis",
      "理由",
      "逻辑",
    ]) ?? "model omitted reasoning";

  return { recommendation, tickers, conviction, reasoning };
}

function normalizeAction(value: string | undefined): MirofishRecommendation["recommendation"] {
  const raw = (value ?? "").trim();
  const lower = raw.toLowerCase();
  if (!raw) throw new Error("recommendation JSON is missing recommendation/action");
  if (
    lower === "buy" ||
    lower.includes("buy") ||
    lower.includes("long") ||
    raw.includes("买入") ||
    raw.includes("做多") ||
    raw.includes("看多") ||
    raw.includes("增持") ||
    raw.includes("加仓")
  ) {
    return "BUY";
  }
  if (
    lower === "sell" ||
    lower.includes("sell") ||
    lower.includes("short") ||
    raw.includes("卖出") ||
    raw.includes("做空") ||
    raw.includes("看空") ||
    raw.includes("减持") ||
    raw.includes("清仓")
  ) {
    return "SELL";
  }
  if (
    lower === "hold" ||
    lower.includes("hold") ||
    lower.includes("neutral") ||
    lower.includes("wait") ||
    raw.includes("持有") ||
    raw.includes("观望") ||
    raw.includes("等待") ||
    raw.includes("不操作") ||
    raw.includes("空仓")
  ) {
    return "HOLD";
  }
  throw new Error(`unsupported recommendation action: ${raw}`);
}

function normalizeTickers(value: unknown, scenario: MirofishScenario): string[] {
  const scenarioTickers = new Set(Object.keys(scenario.price_paths).map((t) => t.toUpperCase()));
  const candidates = valuesToStrings(value)
    .flatMap((s) => s.split(/[,，、;\s]+/))
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);
  const seen = new Set<string>();
  const out: string[] = [];
  for (const ticker of candidates) {
    if (seen.has(ticker)) continue;
    seen.add(ticker);
    if (scenarioTickers.size === 0 || scenarioTickers.has(ticker)) out.push(ticker);
  }
  return out;
}

function normalizeConviction(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value))
    return clamp01(value > 1 ? value / 100 : value);
  if (typeof value === "string") {
    const match = value.match(/-?\d+(?:\.\d+)?/);
    if (match) {
      const parsed = Number(match[0]);
      if (Number.isFinite(parsed))
        return clamp01(value.includes("%") || parsed > 1 ? parsed / 100 : parsed);
    }
  }
  return 0.5;
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function pickValue(record: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) {
    if (key in record && record[key] != null) return record[key];
  }
  return undefined;
}

function pickString(record: Record<string, unknown>, keys: string[]): string | undefined {
  const value = pickValue(record, keys);
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return undefined;
}

function valuesToStrings(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (typeof value === "number") return [String(value)];
  if (Array.isArray(value)) return value.flatMap(valuesToStrings);
  if (isRecord(value)) {
    const nested = pickValue(value, ["ticker", "symbol", "code", "ts_code", "标的", "代码"]);
    return nested == null ? [] : valuesToStrings(nested);
  }
  return [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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
    reflexive = false,
    engine,
    scorer,
    date,
    deps,
    onLog,
  } = opts;
  const log = onLog ?? (() => {});

  const { scenarios: scenes } = await deps.api.mirofishGenerateScenarios({
    num_days: numDays,
    ...(seed != null ? { seed } : {}),
    ...(scenarios ? { scenarios } : {}),
    ...(reflexive ? { reflexivity: true } : {}),
    ...(engine ? { engine } : {}),
  });
  log(
    `generated ${scenes.length} scenarios (${numDays}d${reflexive ? ", reflexive" : ""}${engine ? `, engine=${engine}` : ""})`,
  );

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
        ...(scorer ? { scorer } : {}),
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
