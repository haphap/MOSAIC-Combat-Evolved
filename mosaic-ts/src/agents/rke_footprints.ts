import { createHash } from "node:crypto";
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

interface RkeAudit {
  rke_context_hash?: string;
  ranking_policy_id?: string;
  retrieval_rank?: number;
  priority_bucket?: string;
  truncated_item_count?: number;
  report_claim_refs?: string[];
  tool_refs?: string[];
  rke_prior_usage_quality?: string;
}

interface RkeFootprintBuildOptions {
  currentDataConfirmed?: boolean;
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
  const rows = await buildDailyCycleRkeFootprintRows(api, state, options);
  if (rows.length === 0) return null;
  return api.rkeBenchmarkCaptureAgentClaimFootprints({
    benchmark_run_id: benchmarkRunId,
    rows,
  });
}

export async function buildDailyCycleRkeFootprintRows(
  api: BridgeApi,
  state: DailyCycleStateType,
  options: RkeFootprintBuildOptions = {},
): Promise<RkeAgentClaimFootprintInput[]> {
  const asOfDate = state.as_of_date || new Date().toISOString().slice(0, 10);
  const rows: RkeAgentClaimFootprintInput[] = [];

  for (const [agent, output] of Object.entries(state.layer1_outputs ?? {})) {
    rows.push(
      await rowForAgent(api, asOfDate, "macro", agent, output, "macro_regime_claim", options),
    );
  }
  for (const [agent, output] of Object.entries(state.layer2_outputs ?? {})) {
    rows.push(await rowForAgent(api, asOfDate, "sector", agent, output, "sector_claim", options));
  }
  for (const [agent, output] of Object.entries(state.layer3_outputs ?? {})) {
    rows.push(
      await rowForAgent(
        api,
        asOfDate,
        "superinvestor",
        agent,
        output,
        "style_candidate_claim",
        options,
      ),
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
      await rowForAgent(
        api,
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

async function rowForAgent(
  api: BridgeApi,
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
): Promise<RkeAgentClaimFootprintInput> {
  const audit = await fetchRkeAudit(api, agent, layer, asOfDate);
  const currentDataConfirmed = options.currentDataConfirmed === true && !!audit.rke_context_hash;
  return {
    ...audit,
    agent,
    layer,
    as_of_date: asOfDate,
    claim_type: claimType,
    target: { target_type: layer, target_id: agent },
    confidence_bucket: confidenceBucket(outputConfidence(output)),
    rke_prior_usage_quality: currentDataConfirmed
      ? "used_ranked_prior"
      : (audit.rke_prior_usage_quality ?? "no_ranked_prior_available"),
    current_data_confirmed: currentDataConfirmed,
    stale_prior_rejected: false,
    contradictory_prior_handled: false,
    ...(options.replayRunId ? { replay_run_id: options.replayRunId } : {}),
    ...(options.episodeId ? { episode_id: options.episodeId } : {}),
    ...(options.modelConfigId ? { model_config_id: options.modelConfigId } : {}),
    reason_codes: currentDataConfirmed
      ? ["daily_cycle_runtime_capture", "formal_runtime_current_data_confirmed"]
      : ["daily_cycle_runtime_capture"],
    failure_mode_tags: audit.rke_context_hash ? [] : ["rke_priors_not_yet_informative"],
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

async function fetchRkeAudit(
  api: BridgeApi,
  agent: string,
  layer: string,
  asOfDate: string,
): Promise<RkeAudit> {
  try {
    const context = await api.rkeAgentResearchContext({
      agent_id: agent,
      layer,
      as_of_date: asOfDate,
      max_items: 1,
    });
    const item = context.context_items[0];
    if (!item) {
      return {
        tool_refs: ["rke.agentResearchContext"],
        rke_prior_usage_quality: "no_ranked_prior_available",
      };
    }
    const retrievalRank = Number(item.retrieval_rank);
    const priorityBucket = String(item.priority_bucket ?? "");
    const claimRef = String(item.redacted_claim_id ?? "");
    return {
      ranking_policy_id: context.ranking_policy_id,
      rke_context_hash: createHash("sha256").update(JSON.stringify(context)).digest("hex"),
      ...(Number.isInteger(retrievalRank) && retrievalRank > 0
        ? { retrieval_rank: retrievalRank }
        : {}),
      ...(priorityBucket ? { priority_bucket: priorityBucket } : {}),
      truncated_item_count: Number(context.summary.truncated_item_count ?? 0),
      report_claim_refs: claimRef ? [claimRef] : [],
      tool_refs: ["rke.agentResearchContext"],
      rke_prior_usage_quality: "used_ranked_prior_unconfirmed",
    };
  } catch {
    return {
      tool_refs: ["rke.agentResearchContext"],
      rke_prior_usage_quality: "rke_context_tool_failed",
    };
  }
}

export function parseRkeAudit(text: string): RkeAudit {
  const header = text.match(/ranking_policy_id=([^;]+);\s*context_hash=([a-f0-9]{64});/i);
  const ranking = text.match(
    /retrieval_ranks=([^;]+);\s*priority_buckets=([^;]+);\s*truncated_item_count=(\d+);/i,
  );
  const prior = text.match(/^### Prior\s+(.+)$/m);
  const ranks = (ranking?.[1] ?? "")
    .split(",")
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isInteger(item) && item > 0);
  const buckets = (ranking?.[2] ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  if (!header || ranks.length === 0 || buckets.length === 0) {
    return {
      tool_refs: ["get_rke_research_context"],
      rke_prior_usage_quality: "no_ranked_prior_available",
    };
  }
  const rankingPolicyId = header[1];
  const contextHash = header[2];
  const retrievalRank = ranks[0];
  const priorityBucket = buckets[0];
  if (!rankingPolicyId || !contextHash || !retrievalRank || !priorityBucket) {
    return {
      tool_refs: ["get_rke_research_context"],
      rke_prior_usage_quality: "no_ranked_prior_available",
    };
  }
  return {
    ranking_policy_id: rankingPolicyId,
    rke_context_hash: contextHash.toLowerCase(),
    retrieval_rank: retrievalRank,
    priority_bucket: priorityBucket,
    truncated_item_count: Number(ranking?.[3] ?? 0),
    report_claim_refs: prior?.[1] ? [prior[1].trim()] : [],
    tool_refs: ["get_rke_research_context"],
    rke_prior_usage_quality: "used_ranked_prior_unconfirmed",
  };
}

function confidenceBucket(value: number): string {
  if (value >= 0.67) return "high";
  if (value >= 0.34) return "medium";
  return "low";
}
