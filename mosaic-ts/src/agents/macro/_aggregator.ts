/**
 * Layer-1 aggregator (Plan §5.1 + §11.2 sub-step 2C.3).
 *
 * Collapses the 10 ``MacroAgentOutput`` payloads into a single
 * ``RegimeSignal`` via a deterministic confidence-weighted vote — no
 * second-pass LLM call. This keeps backtests reproducible and lets Phase 5
 * PRISM cohort training compare regime calls without LLM noise drift.
 *
 * Pipeline:
 *   1. Map each agent's stance field to a vote in {-1, 0, +1} via the table
 *      in plan §11.2 2C.3.
 *   2. Weighted average: ``score = sum(vote × conf) / sum(conf)``.
 *   3. Apply ±0.3 threshold to bucket ``score`` into BULLISH / BEARISH /
 *      NEUTRAL. The ±0.3 band is deliberately conservative to suppress
 *      noisy signals (e.g. 6 weak +1 vs 4 weak -1 → score≈+0.2 stays
 *      NEUTRAL, not BULLISH).
 *   4. ``layer_1_consensus_score = mean_confidence × alignment_ratio``
 *      where ``alignment_ratio`` is the fraction of agents whose vote
 *      matches the final stance.
 *   5. ``key_drivers`` = first key_driver from each agent with
 *      confidence > 0.5, ordered as in ``ALL_MACRO_AGENTS``.
 */

import type { DailyCycleStateType, DailyCycleStateUpdate } from "../state.js";
import type {
  CommoditiesOutput,
  DollarOutput,
  EmergingMarketsOutput,
  GeopoliticalOutput,
  InstitutionalFlowOutput,
  MacroAgentOutput,
  NewsSentimentOutput,
  RegimeSignal,
  VolatilityOutput,
  YieldCurveOutput,
} from "../types.js";

/** Canonical macro-agent ID list — Plan §5.1 order. */
export const ALL_MACRO_AGENTS = [
  "central_bank",
  "china",
  "geopolitical",
  "dollar",
  "yield_curve",
  "commodities",
  "volatility",
  "emerging_markets",
  "news_sentiment",
  "institutional_flow",
] as const;

export type Vote = -1 | 0 | 1;

/** Bucket boundary on the weighted score. Tightened from ±0.2 to ±0.3 in 2C.3
 *  to avoid declaring BULLISH/BEARISH from a marginal majority (Plan §11.2). */
export const STANCE_THRESHOLD = 0.3;

// ---------------------------------------------------------------------------
// Stance → vote mapping (Plan §11.2 2C.3 design table)
// ---------------------------------------------------------------------------

export function voteForAgent(out: MacroAgentOutput): Vote {
  switch (out.agent) {
    case "central_bank":
      if (out.stance === "ACCOMMODATIVE") return +1;
      if (out.stance === "TIGHTENING") return -1;
      return 0;

    case "china":
      if (out.policy_direction === "PRO_GROWTH") return +1;
      if (out.policy_direction === "RESTRAINING") return -1;
      return 0;

    case "geopolitical": {
      const o = out as GeopoliticalOutput;
      if (o.escalation_level <= 2) return +1;
      if (o.escalation_level >= 4) return -1;
      return 0;
    }

    case "dollar": {
      const o = out as DollarOutput;
      if (o.dxy_trend === "WEAKENING") return +1;
      if (o.dxy_trend === "STRENGTHENING") return -1;
      return 0;
    }

    case "yield_curve": {
      const o = out as YieldCurveOutput;
      if (o.recession_signal === "GREEN") return +1;
      if (o.recession_signal === "RED") return -1;
      return 0;
    }

    case "commodities": {
      const o = out as CommoditiesOutput;
      if (o.china_demand_signal === "ACCELERATING") return +1;
      if (o.china_demand_signal === "DECELERATING") return -1;
      return 0;
    }

    case "volatility": {
      const o = out as VolatilityOutput;
      if (o.regime_filter === "RISK_ON") return +1;
      if (o.regime_filter === "RISK_OFF") return -1;
      return 0;
    }

    case "emerging_markets": {
      const o = out as EmergingMarketsOutput;
      if (o.em_relative === "OUTPERFORMING") return +1;
      if (o.em_relative === "UNDERPERFORMING") return -1;
      return 0;
    }

    case "news_sentiment": {
      const o = out as NewsSentimentOutput;
      // Contrarian retail euphoria is a bearish signal (institutional selling).
      // Contrarian retail capitulation paired with positive score doesn't
      // happen by construction; treat conservatively as NEUTRAL.
      if (o.contrarian_flag) return o.retail_sentiment_score > 0 ? -1 : 0;
      if (o.retail_sentiment_score > 0.3) return +1;
      if (o.retail_sentiment_score < -0.3) return -1;
      return 0;
    }

    case "institutional_flow": {
      const o = out as InstitutionalFlowOutput;
      // Aggregate net flow across listed sectors. > +1B CNY = bullish.
      const netSum = o.sectors_in_out.reduce((acc, s) => acc + s.net_amount_cny, 0);
      if (netSum > 1000) return +1; // CNY mil → 1B CNY
      if (netSum < -1000) return -1;
      return 0;
    }

    default: {
      // Exhaustive check — TS will flag at compile time if a new agent type
      // is added without updating this switch.
      const _exhaustive: never = out;
      void _exhaustive;
      return 0;
    }
  }
}

// ---------------------------------------------------------------------------
// Pure aggregator
// ---------------------------------------------------------------------------

export interface AggregateLayer1Result {
  signal: RegimeSignal;
  /** Per-agent diagnostics for state-inspection / debug logging. */
  votes: Array<{ agent: string; vote: Vote; confidence: number }>;
}

export function aggregateLayer1(
  outputs: Readonly<Record<string, MacroAgentOutput>>,
): AggregateLayer1Result {
  const votes: Array<{ agent: string; vote: Vote; confidence: number }> = [];
  for (const agent of ALL_MACRO_AGENTS) {
    const out = outputs[agent];
    if (!out) continue;
    votes.push({
      agent,
      vote: voteForAgent(out),
      confidence: out.confidence,
    });
  }

  if (votes.length === 0) {
    return {
      signal: {
        stance: "NEUTRAL",
        confidence: 0,
        key_drivers: ["no macro agent outputs available"],
        layer_1_consensus_score: 0,
      },
      votes: [],
    };
  }

  let weightedSum = 0;
  let totalWeight = 0;
  for (const v of votes) {
    weightedSum += v.vote * v.confidence;
    totalWeight += v.confidence;
  }
  const score = totalWeight > 0 ? weightedSum / totalWeight : 0;

  let stance: RegimeSignal["stance"];
  if (score > STANCE_THRESHOLD) stance = "BULLISH";
  else if (score < -STANCE_THRESHOLD) stance = "BEARISH";
  else stance = "NEUTRAL";

  const meanConfidence = totalWeight / votes.length;
  const alignedCount = votes.filter((v) => alignsWithStance(v.vote, stance)).length;
  const alignmentRatio = alignedCount / votes.length;
  const consensusScore = meanConfidence * alignmentRatio;

  const drivers = ALL_MACRO_AGENTS.flatMap((agent) => {
    const out = outputs[agent];
    if (!out || out.confidence <= 0.5) return [];
    const first = out.key_drivers[0];
    return first ? [`${agent}: ${first}`] : [];
  }).slice(0, 8);

  return {
    signal: {
      stance,
      confidence: Number(meanConfidence.toFixed(3)),
      key_drivers:
        drivers.length > 0 ? drivers : ["no high-confidence drivers across macro agents"],
      layer_1_consensus_score: Number(consensusScore.toFixed(3)),
    },
    votes,
  };
}

function alignsWithStance(vote: Vote, stance: RegimeSignal["stance"]): boolean {
  if (stance === "BULLISH") return vote > 0;
  if (stance === "BEARISH") return vote < 0;
  return vote === 0;
}

// ---------------------------------------------------------------------------
// LangGraph node wrapper
// ---------------------------------------------------------------------------

/**
 * State-graph node that reads ``state.layer1_outputs``, runs the deterministic
 * aggregator, and writes ``layer1_consensus``. Pure function — no I/O — so it
 * doesn't need a deps closure like the agent nodes do.
 */
export async function aggregateLayer1Node(
  state: DailyCycleStateType,
): Promise<DailyCycleStateUpdate> {
  const result = aggregateLayer1(state.layer1_outputs ?? {});
  return { layer1_consensus: result.signal };
}
