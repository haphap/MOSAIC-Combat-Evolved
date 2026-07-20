/**
 * Upstream-state renderers shared across the 4 Layer-4 decision agents.
 * Each L4 agent picks a different subset of these helpers in its
 * ``buildUserContext``.
 */

import {
  type AcceptedAgentOutputRecord,
  type AcceptedAgentOutputStore,
  type AcceptedOutputKind,
  type AcceptedOutputRecordRef,
  acceptedOutputRefKey,
} from "../accepted_output.js";
import { renderAcceptedMacroInputs } from "../helpers/macro_context.js";
import {
  renderAcceptedSectorInputs,
  renderAcceptedSuperinvestorInputs,
} from "../helpers/source_layer_usage.js";
import type { DailyCycleStateType } from "../state.js";
import type { Layer4AgentOutput } from "./_factory.js";
import { type AcceptedDecisionOutput, modelVisibleAcceptedDecision } from "./accepted.js";
import { expectedFrozenOrderIntents, frozenCandidateRef } from "./runtime_adapter.js";

// ---------------------------------------------------------------------------
// Layer 1 — macro regime
// ---------------------------------------------------------------------------

export function renderLayer1Context(
  state: DailyCycleStateType,
  store?: AcceptedAgentOutputStore,
): string {
  return renderAcceptedMacroInputs(state, store);
}

// ---------------------------------------------------------------------------
// Layer 2 — sector picks
// ---------------------------------------------------------------------------

export function renderLayer2Context(
  state: DailyCycleStateType,
  store?: AcceptedAgentOutputStore,
): string {
  return renderAcceptedSectorInputs(state, store);
}

// ---------------------------------------------------------------------------
// Layer 3 — superinvestor picks
// ---------------------------------------------------------------------------

export function renderLayer3Context(
  state: DailyCycleStateType,
  store?: AcceptedAgentOutputStore,
): string {
  return renderAcceptedSuperinvestorInputs(state, store);
}

// ---------------------------------------------------------------------------
// Layer 4 — peer outputs (read by autonomous_execution and cio)
// ---------------------------------------------------------------------------

export function renderLayer4PeerContext(
  state: DailyCycleStateType,
  exclude: ReadonlyArray<keyof Layer4AgentOutput | string> = [],
  store?: AcceptedAgentOutputStore,
): string {
  if (state.darwinian_runtime_binding) {
    if (!store) throw new Error("Decision accepted-output store is required in production");
    return renderAcceptedDecisionPeers(state, exclude, store);
  }
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
  } else if (state.outcome_stage_skips.cro && !exclude.includes("cro")) {
    any = true;
    lines.push("### cro", "* source_status: NO_EVALUATION_OBJECT", "* member_count: 0");
  }

  if (peers.alpha_discovery && !exclude.includes("alpha_discovery")) {
    any = true;
    const novel = peers.alpha_discovery.novel_picks
      .map((p) => `${p.ticker}:${p.why_missed_by_others}`)
      .join(" | ");
    lines.push(`### alpha_discovery (conf=${peers.alpha_discovery.confidence.toFixed(2)})`);
    lines.push(`* novel_picks:       ${novel || "(none)"}`);
  } else if (state.outcome_stage_skips.alpha_discovery && !exclude.includes("alpha_discovery")) {
    any = true;
    lines.push("### alpha_discovery", "* source_status: NO_EVALUATION_OBJECT", "* member_count: 0");
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
  } else if (
    state.outcome_stage_skips.autonomous_execution &&
    !exclude.includes("autonomous_execution")
  ) {
    any = true;
    lines.push(
      "### autonomous_execution",
      "* source_status: NO_EVALUATION_OBJECT",
      "* member_count: 0",
    );
  }

  if (!any) {
    lines.push("* (none of the peer outputs available yet)");
  }
  return lines.join("\n");
}

function renderAcceptedDecisionPeers(
  state: DailyCycleStateType,
  exclude: ReadonlyArray<string>,
  store: AcceptedAgentOutputStore,
): string {
  const lines = ["## Layer-4 accepted peer outputs"];
  const peers: Array<{
    agentId: "alpha_discovery" | "cro" | "autonomous_execution" | "cio";
    kind: AcceptedOutputKind;
  }> = [
    { agentId: "alpha_discovery", kind: "ALPHA_DISCOVERY" },
    { agentId: "cro", kind: "CRO_RISK_REVIEW" },
    { agentId: "autonomous_execution", kind: "EXECUTION_ASSESSMENT" },
    { agentId: "cio", kind: "CIO_PROPOSAL" },
  ];
  let rendered = 0;
  for (const peer of peers) {
    if (exclude.includes(peer.agentId)) continue;
    const ref = state.accepted_output_refs[acceptedOutputRefKey(peer.kind, peer.agentId as never)];
    if (!ref) {
      const skip = peer.agentId === "cio" ? undefined : state.outcome_stage_skips[peer.agentId];
      if (skip) {
        lines.push(
          `### ${peer.agentId}`,
          `* output: ${JSON.stringify({
            agent_id: peer.agentId,
            skip_reason: "NO_EVALUATION_OBJECT",
            member_count: 0,
          })}`,
        );
        rendered += 1;
      }
      continue;
    }
    const record = store.resolve(
      ref as AcceptedOutputRecordRef<typeof peer.kind>,
    ) as AcceptedAgentOutputRecord<typeof peer.kind, AcceptedDecisionOutput>;
    if (
      record.graph_run_id !== state.trace_id ||
      record.as_of !== (state.outcome_schedule_plan?.as_of ?? state.as_of_date)
    ) {
      throw new Error(`${peer.agentId}: accepted Decision peer binding mismatch`);
    }
    lines.push(
      `### ${peer.agentId}`,
      `* output: ${JSON.stringify(modelVisibleAcceptedDecision(record.output.payload))}`,
    );
    rendered += 1;
  }
  if (rendered === 0) lines.push("* (none of the peer outputs available yet)");
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
        `  - candidate_ref=${frozenCandidateRef(runtime.candidate_target_state.candidate_target_hash, action.ticker)}, ` +
          `ts_code=${action.ticker}: ${action.action}, target=${action.target_weight.toFixed(4)}, ` +
          `review_source=${action.review_source ?? "llm"}`,
      );
    }
  }
  if (runtime?.cro_review_state && runtime.candidate_target_state) {
    lines.push(`* cro_review_hash: ${runtime.cro_review_state.review_hash}`);
    lines.push(`* cro_control_source_status: ${runtime.cro_review_state.source_status}`);
    for (const intent of expectedFrozenOrderIntents(
      runtime.candidate_target_state,
      runtime.cro_review_state,
    ).order_intents) {
      lines.push(
        `  - order_intent_ref=${intent.order_intent_ref}, ts_code=${intent.ts_code}, ` +
          `requested_delta_weight=${intent.requested_delta_weight.toFixed(6)}`,
      );
    }
  }
  if (runtime?.execution_feasibility_state) {
    lines.push(
      `* execution_feasibility_hash: ${runtime.execution_feasibility_state.feasibility_hash}`,
    );
    lines.push(
      `* execution_control_source_status: ${runtime.execution_feasibility_state.source_status}`,
    );
    lines.push(
      `* liquidity_vintage_hash: ${runtime.execution_feasibility_state.liquidity_vintage_hash}`,
    );
  }
  return lines.join("\n");
}

export function renderJanusRegimeStub(): string {
  return (
    `## Cohort provenance\n` +
    `* Macro inputs remain ten separate accepted transmissions; no cohort blend or synthetic stance is produced.\n`
  );
}
