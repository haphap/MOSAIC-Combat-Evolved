import type {
  BridgeApi,
  RkeAgentClaimFootprintCaptureResult,
  RkeAgentClaimFootprintInput,
} from "../bridge/types.js";
import type { DailyCycleStateType } from "./state.js";
import type {
  Layer4AgentOutputKey,
  Layer4Outputs,
  MacroAgentOutput,
  SectorAgentOutput,
  SuperinvestorOutput,
} from "./types.js";

type ClaimType =
  | "macro_regime_claim"
  | "sector_claim"
  | "style_candidate_claim"
  | "portfolio_action_claim"
  | "risk_claim";

interface RkeFootprintBuildOptions {
  replayRunId?: string;
  episodeId?: string;
  modelConfigId?: string;
}

export async function captureDailyCycleRkeFootprints(
  api: BridgeApi,
  state: DailyCycleStateType,
  benchmarkRunId = state.trace_id || `daily-cycle-${state.as_of_date || "unknown"}`,
  options: RkeFootprintBuildOptions = {},
): Promise<RkeAgentClaimFootprintCaptureResult | null> {
  const rows = buildDailyCycleRkeFootprintRows(state, options);
  if (rows.length === 0) return null;
  return api.rkeBenchmarkCaptureAgentClaimFootprints({
    benchmark_run_id: benchmarkRunId,
    rows,
  });
}

export function buildDailyCycleRkeFootprintRows(
  state: DailyCycleStateType,
  options: RkeFootprintBuildOptions = {},
): RkeAgentClaimFootprintInput[] {
  const asOfDate = state.as_of_date || new Date().toISOString().slice(0, 10);
  const rows: RkeAgentClaimFootprintInput[] = [];

  for (const [agent, output] of Object.entries(state.layer1_outputs ?? {})) {
    rows.push(rowForAgent(asOfDate, "macro", agent, output, "macro_regime_claim", options));
  }
  for (const [agent, output] of Object.entries(state.layer2_outputs ?? {})) {
    rows.push(rowForAgent(asOfDate, "sector", agent, output, "sector_claim", options));
  }
  for (const [agent, output] of Object.entries(state.layer3_outputs ?? {})) {
    rows.push(
      rowForAgent(asOfDate, "superinvestor", agent, output, "style_candidate_claim", options),
    );
  }
  for (const agent of [
    "cro",
    "alpha_discovery",
    "autonomous_execution",
    "cio",
  ] as const satisfies ReadonlyArray<Layer4AgentOutputKey>) {
    const output = state.layer4_outputs?.[agent];
    if (!output) continue;
    rows.push(
      rowForAgent(
        asOfDate,
        "decision",
        agent,
        output,
        agent === "cro" ? "risk_claim" : "portfolio_action_claim",
        options,
      ),
    );
  }

  return rows;
}

function rowForAgent(
  asOfDate: string,
  layer: "macro" | "sector" | "superinvestor" | "decision",
  agent: string,
  output:
    | MacroAgentOutput
    | SectorAgentOutput
    | SuperinvestorOutput
    | NonNullable<Layer4Outputs[Layer4AgentOutputKey]>,
  claimType: ClaimType,
  options: RkeFootprintBuildOptions,
): RkeAgentClaimFootprintInput {
  // Final outputs do not establish which RKE context was consumed or checked.
  // A later retrieval cannot supply evidence about the completed agent run.
  return {
    agent,
    layer,
    as_of_date: asOfDate,
    claim_type: claimType,
    target: { target_type: layer, target_id: agent },
    confidence_bucket: confidenceBucket(outputConfidence(output)),
    rke_prior_usage_quality: "not_evaluated",
    current_data_confirmed: false,
    stale_prior_rejected: false,
    contradictory_prior_handled: false,
    ...(options.replayRunId ? { replay_run_id: options.replayRunId } : {}),
    ...(options.episodeId ? { episode_id: options.episodeId } : {}),
    ...(options.modelConfigId ? { model_config_id: options.modelConfigId } : {}),
    reason_codes: ["daily_cycle_runtime_capture", "rke_runtime_usage_unverified"],
    failure_mode_tags: [],
  };
}

function outputConfidence(
  output:
    | MacroAgentOutput
    | SectorAgentOutput
    | SuperinvestorOutput
    | NonNullable<Layer4Outputs[Layer4AgentOutputKey]>,
): number {
  if ("confidence" in output && typeof output.confidence === "number") {
    return output.confidence;
  }
  if ("agent" in output && output.agent === "relationship_mapper") {
    return output.predictive_edges.reduce(
      (maximum, edge) => Math.max(maximum, edge.model_confidence),
      0,
    );
  }
  return 0;
}

function confidenceBucket(value: number): string {
  if (value >= 0.67) return "high";
  if (value >= 0.34) return "medium";
  return "low";
}
