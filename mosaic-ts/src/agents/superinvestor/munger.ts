/** munger Layer-3 (Plan §5.3): quality moat / predictable compounding. */

import type { MungerOutput, RegimeSignal } from "../types.js";
import {
  buildLayerThreeAgentNode,
  type LayerThreeAgentDeps,
  type LayerThreeAgentNode,
  type LayerThreeAgentSpec,
} from "./_factory.js";
import { MungerSchema, SUPERINVESTOR_FIELD_NAMES } from "./_schemas.js";

export const REQUIRED_TOOLS = [
  "get_rke_research_context",
  "get_stock_research",
  "get_fundamentals",
  "get_income_statement",
  "get_cashflow",
  "get_balance_sheet",
  "get_stock_data",
] as const;

export const mungerSpec: LayerThreeAgentSpec<MungerOutput> = {
  agentId: "munger",
  schema: MungerSchema,
  fieldNames: SUPERINVESTOR_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderMunger,
  fallback: fallbackMunger,
};

export function buildMungerNode(deps: LayerThreeAgentDeps): LayerThreeAgentNode {
  return buildLayerThreeAgentNode(mungerSpec, deps);
}

export function renderMunger(o: MungerOutput): string {
  const picks = o.picks
    .map((p) => `${p.ticker}(${p.holding_period}, conv=${p.conviction.toFixed(2)})`)
    .join(", ");
  return (
    `munger picks (confidence=${o.confidence.toFixed(2)})\n` +
    `  picks: ${picks || "(none)"}\n` +
    `  philosophy: ${o.philosophy_note}`
  );
}

export function fallbackMunger(text: string, _regime: RegimeSignal | null): MungerOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "munger",
    picks: [],
    philosophy_note: "no wonderful business at a fair price identified from the candidate set.",
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { MungerSchema, SUPERINVESTOR_FIELD_NAMES };
