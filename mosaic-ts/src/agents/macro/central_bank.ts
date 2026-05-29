/**
 * central_bank Layer-1 macro agent (Plan §5.1).
 *
 * Refactored in 2C.1 to use the generic ``buildLayerOneAgentNode`` factory
 * (Plan §11.2 sub-step 2C-1). The 2-phase semantics (tool-bound analysis →
 * structured extraction) live in the factory; this file only carries the
 * agent-specific spec.
 *
 * Tools (Plan §5.1):
 *   * get_pboc_ops          — PBOC OMO / MLF / SLF
 *   * get_fred_series       — FRED FEDFUNDS / DFF
 *   * get_yield_curve_cn    — China treasury curve, used as PBOC transmission proxy
 */

import type { CentralBankOutput } from "../types.js";
import {
  buildLayerOneAgentNode,
  buildUserContext,
  type LayerOneAgentDeps,
  type LayerOneAgentNode,
  type LayerOneAgentSpec,
  pickPromptLanguage,
} from "./_factory.js";
import { CENTRAL_BANK_FIELD_NAMES, CentralBankSchema } from "./_schemas.js";

// ---------------------------------------------------------------------------
// Spec
// ---------------------------------------------------------------------------

export const REQUIRED_TOOLS = ["get_pboc_ops", "get_fred_series", "get_yield_curve_cn"] as const;

export const centralBankSpec: LayerOneAgentSpec<CentralBankOutput> = {
  agentId: "central_bank",
  schema: CentralBankSchema,
  fieldNames: CENTRAL_BANK_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderCentralBank,
  fallback: fallbackOutputFromText,
};

// ---------------------------------------------------------------------------
// Public node builder
// ---------------------------------------------------------------------------

export function buildCentralBankNode(deps: LayerOneAgentDeps): LayerOneAgentNode {
  return buildLayerOneAgentNode(centralBankSpec, deps);
}

// ---------------------------------------------------------------------------
// Renderer + fallback (kept agent-specific)
// ---------------------------------------------------------------------------

export function renderCentralBank(o: CentralBankOutput): string {
  const drivers = (o.key_drivers ?? []).map((d) => `  - ${d}`).join("\n");
  return (
    `central_bank analysis (confidence=${o.confidence.toFixed(2)})\n` +
    `  stance:                 ${o.stance}\n` +
    `  key_rate_change_bps:    ${o.key_rate_change_bps}\n` +
    `  qe_qt_balance_change:   ${o.qe_qt_balance_change}\n` +
    `  next_window:            ${o.next_window}\n` +
    `  key_drivers:\n${drivers}`
  );
}

export function fallbackOutputFromText(text: string): CentralBankOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "central_bank",
    stance: "NEUTRAL",
    key_rate_change_bps: 0,
    qe_qt_balance_change: trimmed
      ? "extraction failed; free-text analysis preserved"
      : "no analysis produced",
    next_window: "unknown",
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

// ---------------------------------------------------------------------------
// Re-exports for test ergonomics + 2C.2 / 2D / 2E consumers.
// ---------------------------------------------------------------------------

// pickPromptLanguage / buildUserContext live on the factory now; re-exporting
// here keeps callers that imported them from central_bank.ts working.
export { buildUserContext, CENTRAL_BANK_FIELD_NAMES, CentralBankSchema, pickPromptLanguage };
