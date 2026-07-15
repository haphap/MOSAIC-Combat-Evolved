import type { BridgeApi, DarwinianWeightTable, MosaicConfig } from "../../bridge/index.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../state.js";
import type { MacroAgentId, MacroAgentOutput, RegimeSignal } from "../types.js";
import { MACRO_AGENT_IDS } from "./_contracts.js";

export const ALL_MACRO_AGENTS = MACRO_AGENT_IDS;
export const STANCE_THRESHOLD = 0.3;

export const MACRO_FACTOR_GROUPS = {
  china_economy: ["china"],
  us_economy: ["us_economy"],
  policy_liquidity: ["central_bank"],
  financial_conditions: ["dollar", "yield_curve"],
  exogenous_real_shocks: ["commodities", "geopolitical"],
  market_confirmation: ["volatility", "market_breadth", "institutional_flow"],
} as const satisfies Readonly<Record<string, ReadonlyArray<MacroAgentId>>>;

export type MacroFactorGroupId = keyof typeof MACRO_FACTOR_GROUPS;

export class MacroAggregationRejectedError extends Error {
  readonly missingAgents: ReadonlyArray<MacroAgentId>;

  constructor(missingAgents: ReadonlyArray<MacroAgentId>) {
    super(
      `formal macro aggregation requires all 10 accepted agents; missing: ${missingAgents.join(", ")}`,
    );
    this.name = "MacroAggregationRejectedError";
    this.missingAgents = missingAgents;
  }
}

export function signalForAgent(output: MacroAgentOutput): number {
  const sign = output.direction === "SUPPORTIVE" ? 1 : output.direction === "ADVERSE" ? -1 : 0;
  return sign * (output.strength / 5);
}

/** Backward-compatible name for scorecard/test callers; now returns s_i in [-1, 1]. */
export const voteForAgent = signalForAgent;

export interface AggregateLayer1Options {
  darwinianWeights?: DarwinianWeightTable | Record<string, { weight: number }> | null;
}

export interface AgentAggregationDiagnostic {
  agent: MacroAgentId;
  group: MacroFactorGroupId;
  signal: number;
  confidence: number;
  darwinian_weight: number;
  effective_reliability: number;
}

export interface GroupAggregationDiagnostic {
  group: MacroFactorGroupId;
  agent_count: number;
  direction: number;
  reliability: number;
  effective_weight: number;
}

export interface AggregateLayer1Result {
  signal: RegimeSignal;
  score: number;
  votes: AgentAggregationDiagnostic[];
  groups: GroupAggregationDiagnostic[];
}

function groupForAgent(agent: MacroAgentId): MacroFactorGroupId {
  for (const [group, agents] of Object.entries(MACRO_FACTOR_GROUPS)) {
    if ((agents as ReadonlyArray<MacroAgentId>).includes(agent)) return group as MacroFactorGroupId;
  }
  throw new Error(`macro factor group missing for ${agent}`);
}

export function aggregateLayer1(
  outputs: Readonly<Record<string, MacroAgentOutput>>,
  options: AggregateLayer1Options = {},
): AggregateLayer1Result {
  const missing = ALL_MACRO_AGENTS.filter((agent) => {
    const output = outputs[agent];
    return !output || output.agent !== agent;
  });
  if (missing.length > 0) throw new MacroAggregationRejectedError(missing);

  const votes = ALL_MACRO_AGENTS.map((agent): AgentAggregationDiagnostic => {
    const output = outputs[agent] as MacroAgentOutput;
    const configured = options.darwinianWeights?.[agent]?.weight;
    const darwinianWeight =
      Number.isFinite(configured) && Number(configured) > 0 ? Number(configured) : 1.0;
    return {
      agent,
      group: groupForAgent(agent),
      signal: signalForAgent(output),
      confidence: output.confidence,
      darwinian_weight: darwinianWeight,
      effective_reliability: output.confidence * darwinianWeight,
    };
  });

  const groups = (Object.keys(MACRO_FACTOR_GROUPS) as MacroFactorGroupId[]).map(
    (group): GroupAggregationDiagnostic => {
      const members = votes.filter((vote) => vote.group === group);
      const totalReliability = members.reduce(
        (total, member) => total + member.effective_reliability,
        0,
      );
      const direction =
        totalReliability > 0
          ? members.reduce(
              (total, member) => total + member.effective_reliability * member.signal,
              0,
            ) / totalReliability
          : 0;
      return {
        group,
        agent_count: members.length,
        direction,
        reliability: totalReliability / members.length,
        effective_weight: 0,
      };
    },
  );

  const reliabilityDenominator = groups.reduce((total, group) => total + group.reliability, 0);
  for (const group of groups) {
    group.effective_weight =
      reliabilityDenominator > 0 ? group.reliability / reliabilityDenominator : 1 / groups.length;
  }
  const score = groups.reduce(
    (total, group) => total + group.effective_weight * group.direction,
    0,
  );
  const stance: RegimeSignal["stance"] =
    score > STANCE_THRESHOLD ? "BULLISH" : score < -STANCE_THRESHOLD ? "BEARISH" : "NEUTRAL";
  const meanGroupReliability =
    groups.reduce((total, group) => total + group.reliability, 0) / groups.length;
  const keyDrivers = votes
    .slice()
    .sort((a, b) => b.effective_reliability - a.effective_reliability)
    .flatMap((vote) => {
      const driver = outputs[vote.agent]?.key_drivers[0];
      return driver ? [`${vote.agent}: ${driver}`] : [];
    })
    .slice(0, 8);

  return {
    score,
    signal: {
      stance,
      confidence: Number(Math.min(1, meanGroupReliability).toFixed(3)),
      key_drivers: keyDrivers,
      layer_1_consensus_score: Number(score.toFixed(3)),
    },
    votes,
    groups,
  };
}

export async function aggregateLayer1Node(
  state: DailyCycleStateType,
): Promise<DailyCycleStateUpdate> {
  return { layer1_consensus: aggregateLayer1(state.layer1_outputs ?? {}).signal };
}

export interface BuildAggregateLayer1NodeDeps {
  api?: Pick<BridgeApi, "darwinianGetWeights">;
  config?: MosaicConfig;
  onLog?: (message: string) => void;
}

export function buildAggregateLayer1Node(deps: BuildAggregateLayer1NodeDeps = {}) {
  return async (state: DailyCycleStateType): Promise<DailyCycleStateUpdate> => {
    let darwinianWeights: DarwinianWeightTable | undefined;
    if (deps.config?.darwinian?.weight_rewrite_enabled && deps.api) {
      try {
        darwinianWeights = (
          await deps.api.darwinianGetWeights(state.active_cohort, state.as_of_date || undefined)
        ).weights;
      } catch (error) {
        deps.onLog?.(`aggregate_l1: darwinian weights unavailable: ${(error as Error).message}`);
      }
    }
    const result = aggregateLayer1(
      state.layer1_outputs ?? {},
      darwinianWeights ? { darwinianWeights } : {},
    );
    return { layer1_consensus: result.signal };
  };
}
