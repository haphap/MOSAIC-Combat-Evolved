/**
 * Upstream-state renderers shared across the 4 Layer-4 decision agents.
 * Each L4 agent picks a different subset of these helpers in its
 * ``buildUserContext``.
 */

import type { DailyCycleStateType } from "../state.js";
import type { Layer4AgentOutput } from "./_factory.js";

// ---------------------------------------------------------------------------
// Layer 1 — macro regime
// ---------------------------------------------------------------------------

export function renderLayer1Context(state: DailyCycleStateType): string {
  const regime = state.layer1_consensus;
  if (!regime) {
    return "## Layer-1 macro regime\n* (not available — state.layer1_consensus is null)\n";
  }
  return (
    `## Layer-1 macro regime\n` +
    `* stance:                   ${regime.stance}\n` +
    `* confidence:               ${regime.confidence.toFixed(2)}\n` +
    `* layer_1_consensus_score:  ${regime.layer_1_consensus_score.toFixed(2)}\n` +
    `* key_drivers:\n${regime.key_drivers.map((d) => `  - ${d}`).join("\n")}\n`
  );
}

// ---------------------------------------------------------------------------
// Layer 2 — sector picks
// ---------------------------------------------------------------------------

export function renderLayer2Context(state: DailyCycleStateType): string {
  const sectors = state.layer2_outputs ?? {};
  const lines: string[] = ["## Layer-2 sector picks"];
  if (Object.keys(sectors).length === 0) {
    lines.push("* (not available — state.layer2_outputs is empty)");
    return lines.join("\n");
  }

  for (const [sectorId, out] of Object.entries(sectors)) {
    if (out.agent === "relationship_mapper") {
      const chains = out.supply_chains
        .map((c) => `${c.name}=[${c.tickers.join(",")}](${c.risk})`)
        .join("; ");
      const risks = out.contagion_risks.join(" | ");
      lines.push(`### ${sectorId} (cross-sector)`);
      lines.push(`* supply_chains:    ${chains || "(none)"}`);
      lines.push(`* contagion_risks:  ${risks || "(none)"}`);
    } else {
      const longs = out.longs
        .slice(0, 5)
        .map((p) => `${p.ticker}(${p.conviction.toFixed(2)})`)
        .join(", ");
      const shorts = out.shorts
        .slice(0, 5)
        .map((p) => `${p.ticker}(${p.conviction.toFixed(2)})`)
        .join(", ");
      lines.push(
        `### ${sectorId} (score=${out.sector_score.toFixed(2)}, conf=${out.confidence.toFixed(2)})`,
      );
      lines.push(`* longs:  ${longs || "(none)"}`);
      lines.push(`* shorts: ${shorts || "(none)"}`);
    }
  }
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Layer 3 — superinvestor picks
// ---------------------------------------------------------------------------

export function renderLayer3Context(state: DailyCycleStateType): string {
  const supers = state.layer3_outputs ?? {};
  const lines: string[] = ["## Layer-3 superinvestor picks"];
  if (Object.keys(supers).length === 0) {
    lines.push("* (not available — state.layer3_outputs is empty)");
    return lines.join("\n");
  }
  for (const [agentId, out] of Object.entries(supers)) {
    const picks = out.picks
      .map((p) => `${p.ticker}(${p.holding_period},conv=${p.conviction.toFixed(2)})`)
      .join(", ");
    lines.push(`### ${agentId} (conf=${out.confidence.toFixed(2)})`);
    lines.push(`* picks:           ${picks || "(none)"}`);
    lines.push(`* philosophy:      ${out.philosophy_note}`);
  }
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Layer 4 — peer outputs (read by autonomous_execution and cio)
// ---------------------------------------------------------------------------

export function renderLayer4PeerContext(
  state: DailyCycleStateType,
  exclude: ReadonlyArray<keyof Layer4AgentOutput | string> = [],
): string {
  const peers = state.layer4_outputs ?? {};
  const lines: string[] = ["## Layer-4 peer outputs"];
  let any = false;

  if (peers.cro && !exclude.includes("cro")) {
    any = true;
    const rejected = peers.cro.rejected_picks.map((r) => `${r.ticker}:${r.reason}`).join(" | ");
    lines.push(`### cro (conf=${peers.cro.confidence.toFixed(2)})`);
    lines.push(`* rejected_picks:    ${rejected || "(none)"}`);
    lines.push(`* correlated_risks:  ${peers.cro.correlated_risks.join(" | ")}`);
    lines.push(`* black_swans:       ${peers.cro.black_swan_scenarios.join(" | ")}`);
  }

  if (peers.alpha_discovery && !exclude.includes("alpha_discovery")) {
    any = true;
    const novel = peers.alpha_discovery.novel_picks
      .map((p) => `${p.ticker}:${p.why_missed_by_others}`)
      .join(" | ");
    lines.push(`### alpha_discovery (conf=${peers.alpha_discovery.confidence.toFixed(2)})`);
    lines.push(`* novel_picks:       ${novel || "(none)"}`);
  }

  if (peers.autonomous_execution && !exclude.includes("autonomous_execution")) {
    any = true;
    const trades = peers.autonomous_execution.trades
      .map(
        (t) => `${t.ticker}:${t.action}@${t.size_pct.toFixed(2)}(conv=${t.conviction.toFixed(2)})`,
      )
      .join(" | ");
    lines.push(
      `### autonomous_execution (conf=${peers.autonomous_execution.confidence.toFixed(2)})`,
    );
    lines.push(`* trades:            ${trades || "(none)"}`);
  }

  if (!any) {
    lines.push("* (none of the peer outputs available yet)");
  }
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Stub helpers for Phase 3+ / Phase 6+ data.
// ---------------------------------------------------------------------------

export function renderDarwinianWeightsStub(): string {
  return (
    `## Darwinian weights\n` +
    `* (Phase 3 stub — using uniform weight 1/N across upstream picks. ` +
    `Phase 3 scorecard will replace this.)\n`
  );
}

export function renderJanusRegimeStub(): string {
  return (
    `## JANUS multi-cohort regime\n` +
    `* (Phase 6 stub — using single-cohort layer1_consensus directly. ` +
    `Phase 6 will replace this with the multi-cohort blend.)\n`
  );
}
