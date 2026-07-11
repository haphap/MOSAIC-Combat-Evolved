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

export function renderCurrentPositionsContext(state: DailyCycleStateType): string {
  const snapshot = state.current_positions ?? {
    snapshot_status: "missing" as const,
    position_snapshot_hash: undefined,
    positions: [],
  };
  const lines = [
    "## Current portfolio",
    `* snapshot_status: ${snapshot.snapshot_status}`,
    `* snapshot_hash: ${snapshot.position_snapshot_hash ?? "(missing)"}`,
  ];
  if (snapshot.positions.length === 0) {
    lines.push("* positions: (none)");
    return lines.join("\n");
  }
  for (const position of snapshot.positions) {
    lines.push(
      `* ${position.ticker}: weight=${position.current_weight.toFixed(4)}, ` +
        `price=${position.market_price}, pnl=${position.unrealized_pnl_pct.toFixed(4)}, ` +
        `holding_days=${position.holding_days}, thesis=${position.entry_thesis_id}, ` +
        `last_review=${position.last_review_date}`,
    );
  }
  return lines.join("\n");
}

export function renderPreviousTargetContext(state: DailyCycleStateType): string {
  const previous = state.layer4_outputs?.previous_target_state;
  const lines = ["## Previous final target"];
  if (!previous) {
    lines.push("* snapshot_status: missing", "* source_error: previous_target_state_not_supplied");
    return lines.join("\n");
  }
  lines.push(
    `* snapshot_status: ${previous.snapshot_status}`,
    `* final_target_hash: ${previous.final_target_hash ?? "(missing)"}`,
    `* as_of_date: ${previous.as_of_date ?? "(missing)"}`,
  );
  for (const action of previous.portfolio_actions) {
    lines.push(`* ${action.ticker}: ${action.action}, target=${action.target_weight.toFixed(4)}`);
  }
  return lines.join("\n");
}

export function renderLayer4RuntimeContext(state: DailyCycleStateType): string {
  const runtime = state.layer4_outputs.runtime;
  const lines = ["## Frozen Layer-4 runtime state"];
  if (!runtime?.candidate_target_state) {
    lines.push("* candidate_target_state: (missing)");
  } else {
    lines.push(`* candidate_target_hash: ${runtime.candidate_target_state.candidate_target_hash}`);
    lines.push(
      `* market_data_vintage_hash: ${runtime.candidate_target_state.market_data_vintage_hash}`,
    );
    for (const action of runtime.candidate_target_state.portfolio_actions) {
      lines.push(
        `  - candidate ${action.ticker}: ${action.action}, target=${action.target_weight.toFixed(4)}, ` +
          `review_source=${action.review_source ?? "llm"}`,
      );
    }
  }
  if (runtime?.cro_review_state) {
    lines.push(`* cro_review_hash: ${runtime.cro_review_state.review_hash}`);
  }
  if (runtime?.execution_feasibility_state) {
    lines.push(
      `* execution_feasibility_hash: ${runtime.execution_feasibility_state.feasibility_hash}`,
    );
    lines.push(
      `* liquidity_vintage_hash: ${runtime.execution_feasibility_state.liquidity_vintage_hash}`,
    );
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

/**
 * Real Darwinian weights renderer (Plan §11.3 sub-step 3F).
 *
 * ``weights`` shape matches ``DarwinianWeightTable`` from the bridge:
 *   ``{ <agent>: { weight, sharpe_30, sharpe_90, quartile } }``.
 *
 * Empty / undefined input falls through to the stub renderer so the
 * autonomous_execution prompt always sees a coherent block. This matches
 * Plan §11.3 design decision #7 — the first ~30 days of any cohort have
 * insufficient data to compute Sharpe, so weight=1.0 uniform is the
 * legitimate fallback (equivalent to the Phase 2 stub behaviour).
 */
export function renderDarwinianWeights(
  weights:
    | Record<string, { weight: number; sharpe_30: number | null; quartile: number | null }>
    | undefined,
  date?: string,
): string {
  if (!weights || Object.keys(weights).length === 0) {
    return renderDarwinianWeightsStub();
  }

  const entries = Object.entries(weights).sort((a, b) => b[1].weight - a[1].weight);
  const lines: string[] = [
    `## Darwinian weights${date ? ` (${date})` : ""}`,
    `* Per-agent multiplier in [0.3, 2.5] from rolling 30d Sharpe.`,
    `* Use these to size your trades — overweight agents in quartile 1, underweight quartile 4.`,
  ];
  for (const [agent, w] of entries) {
    const sharpe = w.sharpe_30 === null ? "n<5" : w.sharpe_30.toFixed(2);
    const q = w.quartile === null ? "?" : `Q${w.quartile}`;
    lines.push(`  - ${agent}: weight=${w.weight.toFixed(2)}, sharpe_30=${sharpe} (${q})`);
  }
  return lines.join("\n");
}

export function renderJanusRegimeStub(): string {
  return (
    `## JANUS multi-cohort regime\n` +
    `* (Phase 6 stub — using single-cohort layer1_consensus directly. ` +
    `Phase 6 will replace this with the multi-cohort blend.)\n`
  );
}
