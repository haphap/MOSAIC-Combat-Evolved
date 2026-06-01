/** aschenbrenner Layer-3 (Plan §5.3): AI capex / 算力 cycle vs US export controls. */

import type { AschenbrennerOutput, RegimeSignal } from "../types.js";
import {
  buildLayerThreeAgentNode,
  type LayerThreeAgentDeps,
  type LayerThreeAgentNode,
  type LayerThreeAgentSpec,
} from "./_factory.js";
import { AschenbrennerSchema, SUPERINVESTOR_FIELD_NAMES } from "./_schemas.js";

export const REQUIRED_TOOLS = [
  "get_industry_policy",
  "get_xueqiu_heat",
  "get_stock_research",
  "get_fundamentals",
] as const;

export const aschenbrennerSpec: LayerThreeAgentSpec<AschenbrennerOutput> = {
  agentId: "aschenbrenner",
  schema: AschenbrennerSchema,
  fieldNames: SUPERINVESTOR_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderAschenbrenner,
  fallback: fallbackAschenbrenner,
};

export function buildAschenbrennerNode(deps: LayerThreeAgentDeps): LayerThreeAgentNode {
  return buildLayerThreeAgentNode(aschenbrennerSpec, deps);
}

export function renderAschenbrenner(o: AschenbrennerOutput): string {
  const picks = o.picks
    .map((p) => `${p.ticker}(${p.holding_period}, conv=${p.conviction.toFixed(2)})`)
    .join(", ");
  return (
    `aschenbrenner picks (confidence=${o.confidence.toFixed(2)})\n` +
    `  picks: ${picks || "(none)"}\n` +
    `  philosophy: ${o.philosophy_note}`
  );
}

export function fallbackAschenbrenner(
  text: string,
  _regime: RegimeSignal | null,
): AschenbrennerOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "aschenbrenner",
    picks: [],
    philosophy_note:
      "no AI capex beneficiary identified — domestic compute / AI app candidates absent from upstream.",
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { AschenbrennerSchema, SUPERINVESTOR_FIELD_NAMES };
