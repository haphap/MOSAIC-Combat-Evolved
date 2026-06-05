/**
 * china Layer-1 macro agent (Plan §5.1).
 *
 * Uses the ``buildLayerOneAgentNode`` factory (Plan §11.2 sub-step 2C-1).
 * This file demonstrates the full template the remaining 8 macro agents
 * will follow in 2C.2.
 *
 * Tools (Plan §5.1 / §11.2 design note 2C-4):
 *   * get_industry_policy   — gov.cn policy documents (primary evidence)
 *   * get_pboc_ops          — OMO corroborator
 *   * get_property_data     — 国房景气指数 (real-estate climate; primary A-share
 *                             macro driver — closes the plan §14 #8 gap)
 */

import type { ChinaOutput } from "../types.js";
import {
  buildLayerOneAgentNode,
  type LayerOneAgentDeps,
  type LayerOneAgentNode,
  type LayerOneAgentSpec,
} from "./_factory.js";
import { CHINA_FIELD_NAMES, ChinaSchema } from "./_schemas.js";

// ---------------------------------------------------------------------------
// Spec
// ---------------------------------------------------------------------------

export const REQUIRED_TOOLS = ["get_industry_policy", "get_pboc_ops", "get_property_data"] as const;

export const chinaSpec: LayerOneAgentSpec<ChinaOutput> = {
  agentId: "china",
  schema: ChinaSchema,
  fieldNames: CHINA_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderChina,
  fallback: fallbackChinaOutput,
};

// ---------------------------------------------------------------------------
// Public node builder
// ---------------------------------------------------------------------------

export function buildChinaNode(deps: LayerOneAgentDeps): LayerOneAgentNode {
  return buildLayerOneAgentNode(chinaSpec, deps);
}

// ---------------------------------------------------------------------------
// Renderer + fallback
// ---------------------------------------------------------------------------

export function renderChina(o: ChinaOutput): string {
  const sectors = (o.sector_focus ?? []).join(", ");
  const risks = (o.risk_drivers ?? []).join(", ");
  const drivers = (o.key_drivers ?? []).map((d) => `  - ${d}`).join("\n");
  return (
    `china analysis (confidence=${o.confidence.toFixed(2)})\n` +
    `  policy_direction:    ${o.policy_direction}\n` +
    `  sector_focus:        ${sectors}\n` +
    `  risk_drivers:        ${risks}\n` +
    `  key_drivers:\n${drivers}`
  );
}

export function fallbackChinaOutput(text: string): ChinaOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "china",
    policy_direction: "BALANCED",
    sector_focus: ["unknown"],
    risk_drivers: ["analysis missing"],
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

// ---------------------------------------------------------------------------
// Re-exports
// ---------------------------------------------------------------------------

export { CHINA_FIELD_NAMES, ChinaSchema };
