/**
 * institutional_flow Layer-1 macro agent (Plan §5.1).
 *
 * Tools: `get_lhb_ranking` + `get_stock_moneyflow` (主力资金) + `get_fund_flow`.
 * (Northbound 沪深港通 flow was dropped — live quota disclosure discontinued;
 * main-funds money flow now carries the "big money" signal.)
 */

import type { InstitutionalFlowOutput } from "../types.js";
import {
  buildLayerOneAgentNode,
  type LayerOneAgentDeps,
  type LayerOneAgentNode,
  type LayerOneAgentSpec,
} from "./_factory.js";
import { INSTITUTIONAL_FLOW_FIELD_NAMES, InstitutionalFlowSchema } from "./_schemas.js";

export const REQUIRED_TOOLS = ["get_lhb_ranking", "get_fund_flow", "get_stock_moneyflow"] as const;

export const institutionalFlowSpec: LayerOneAgentSpec<InstitutionalFlowOutput> = {
  agentId: "institutional_flow",
  schema: InstitutionalFlowSchema,
  fieldNames: INSTITUTIONAL_FLOW_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderInstitutionalFlow,
  fallback: fallbackInstitutionalFlow,
};

export function buildInstitutionalFlowNode(deps: LayerOneAgentDeps): LayerOneAgentNode {
  return buildLayerOneAgentNode(institutionalFlowSpec, deps);
}

export function renderInstitutionalFlow(o: InstitutionalFlowOutput): string {
  const buyers = (o.top_buyers ?? []).join(", ");
  const sectors = (o.sectors_in_out ?? [])
    .map((s) => `${s.sector}=${s.net_amount_cny.toFixed(1)}`)
    .join(", ");
  const drivers = (o.key_drivers ?? []).map((d) => `  - ${d}`).join("\n");
  return (
    `institutional_flow analysis (confidence=${o.confidence.toFixed(2)})\n` +
    `  main_net_flow_cny:   ${o.main_net_flow_cny.toFixed(1)} CNY mil\n` +
    `  top_buyers:          ${buyers}\n` +
    `  sectors_in_out:      ${sectors}\n` +
    `  key_drivers:\n${drivers}`
  );
}

export function fallbackInstitutionalFlow(text: string): InstitutionalFlowOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "institutional_flow",
    main_net_flow_cny: 0,
    top_buyers: ["unknown"],
    sectors_in_out: [{ sector: "unknown", net_amount_cny: 0 }],
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { INSTITUTIONAL_FLOW_FIELD_NAMES, InstitutionalFlowSchema };
