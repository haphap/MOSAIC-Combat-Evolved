import type { BaseMessage } from "@langchain/core/messages";
import { z } from "zod";
import { MACRO_AGENT_IDS, MACRO_ROLE_CONTRACTS } from "../agents/macro/_contracts.js";
import {
  STANDARD_SECTOR_AGENT_IDS,
  STANDARD_SECTOR_ROLE_CONTRACTS,
} from "../agents/sector/_contracts.js";
import type { MacroAgentId, StandardSectorAgentId } from "../agents/types.js";

/** Deterministic schema-driven fake used only by CLI smoke runs. */
export function fakeAgentStructuredOutput(
  schema: unknown,
  name: string,
  messages: unknown,
): unknown {
  const jsonSchema = normalizeJsonSchema(schema);
  const output = synthesize(jsonSchema) as Record<string, unknown>;
  const macroAgent = MACRO_AGENT_IDS.find(
    (candidate) => name === candidate || name.startsWith(`${candidate}_`),
  );
  if (macroAgent) {
    return fakeMacroSubmission(macroAgent, messages);
  }
  const sectorAgent = STANDARD_SECTOR_AGENT_IDS.find(
    (candidate) => name === candidate || name.startsWith(`${candidate}_`),
  );
  if (sectorAgent) {
    if (
      schemaMentionsProperty(jsonSchema, "research_mode") ||
      schemaMentionsConst(jsonSchema, "SECTOR_DIRECTION_RESEARCH_COMPACT_V1") ||
      schemaMentionsConst(jsonSchema, "SECTOR_SINGLE_DIRECTION_COMPACT_V1") ||
      schemaMentionsConst(jsonSchema, "SECTOR_CONFLICT_REVIEW_COMPACT_V1")
    ) {
      return fakeSectorDirectionResearch(sectorAgent, messages);
    }
    if (schemaMentionsProperty(jsonSchema, "final_selection")) {
      return { final_selection: fakeSectorSubmission(sectorAgent, messages, true) };
    }
    return fakeSectorSubmission(sectorAgent, messages, false);
  }
  if (name === "relationship_mapper" || name.startsWith("relationship_mapper_")) {
    return fakeRelationshipSubmission(messages);
  }
  const superinvestorAgent = ["druckenmiller", "munger", "burry", "ackman"].find(
    (candidate) => name === candidate || name.startsWith(`${candidate}_`),
  );
  if (superinvestorAgent) {
    return fakeSuperinvestorSubmission(superinvestorAgent, messages);
  }
  const decisionAgent = ["cro", "alpha_discovery", "autonomous_execution", "cio"].find(
    (candidate) => name === candidate || name.startsWith(`${candidate}_`),
  );
  if (decisionAgent) {
    return fakeDecisionSubmission(decisionAgent, messages, jsonSchema);
  }
  if ("direction" in output && "strength" in output) {
    output.direction = "NEUTRAL";
    output.strength = 0;
    if ("horizon" in output) output.horizon = "WEEKS";
  }
  if (!("claims" in output)) return output;
  const text = messageText(messages);
  const evidenceId = firstEvidenceId(text);
  const claimId = `fake-claim-${name}`;
  const positions = currentPositions(text);
  const explicitEmpty = configureDisposition(output, positions, claimId);
  output.claims = [
    evidenceId && !explicitEmpty
      ? {
          claim_id: claimId,
          claim_kind: "FACT",
          statement: "Fake smoke output is bound to the runtime evidence snapshot.",
          structured_conclusion: { disposition: dispositionOf(output) },
          evidence_ids: [evidenceId],
          research_rule_refs: [],
        }
      : {
          claim_id: claimId,
          claim_kind: "RISK_FLAG",
          statement: "Fake smoke found no evidence-supported actionable conclusion.",
          structured_conclusion: { disposition: dispositionOf(output) },
          evidence_ids: evidenceId ? [evidenceId] : [],
          research_rule_refs: [],
        },
  ];
  output.claim_refs = [claimId];
  if ("decision_claim_refs" in output) output.decision_claim_refs = [claimId];
  attachEntryClaimRefs(output, claimId);
  return output;
}

function fakeDecisionSubmission(name: string, messages: unknown, schema: unknown): unknown {
  const text = messageText(messages);
  const evidenceId = firstEvidenceId(text);
  const claimId = `fake-claim-${name}`;
  const claims = [
    {
      claim_id: claimId,
      claim_kind: "FACT",
      statement: "Fake structural Decision output is bound to the frozen runtime input.",
      structured_conclusion: { agent_id: name },
      evidence_ids: evidenceId ? [evidenceId] : [],
      research_rule_refs: [],
    },
  ];
  const macro_input_attributions = MACRO_AGENT_IDS.map((agentId) => ({
    agent_id: agentId,
    target_type: "SUBMISSION_SUMMARY",
    target_local_ref: "$SUBMISSION",
    claim_refs_used: [],
    effect: "NOT_MATERIAL",
  }));
  if (name === "alpha_discovery") {
    return {
      agent_id: "alpha_discovery",
      discovery_disposition: "NONE_FOUND",
      novel_picks: [],
      key_drivers: [
        {
          driver_local_id: "fake-alpha-driver",
          summary: "No frozen novel candidate qualifies in structural smoke.",
          claim_refs: [claimId],
        },
      ],
      risks: [
        {
          risk_local_id: "fake-alpha-risk",
          summary: "Inventing a candidate would cross the frozen universe boundary.",
          claim_refs: [claimId],
        },
      ],
      confidence: 0.5,
      claims,
      claim_refs: [claimId],
      macro_input_attributions,
    };
  }
  if (name === "cro") {
    const candidates = frozenCandidates(text);
    return {
      agent_id: "cro",
      review_disposition: "NO_OBJECTION",
      candidate_actions: candidates.map((candidate, index) => ({
        action_local_id: `fake-cro-action-${index}`,
        candidate_ref: candidate.candidate_ref,
        ts_code: candidate.ts_code,
        action: "NO_OBJECTION",
        predicted_risk_probability: 0.2,
        max_target_weight: null,
        reason: "No structural risk objection is present in the fake snapshot.",
        claim_refs: [claimId],
      })),
      correlated_risks: [],
      black_swan_scenarios: [],
      confidence: 0.5,
      claims,
      claim_refs: [claimId],
      macro_input_attributions,
    };
  }
  if (name === "autonomous_execution") {
    const intents = frozenOrderIntents(text);
    if (intents.length === 0) {
      intents.push({
        order_intent_ref: "fake-order-intent",
        ts_code: "600000.SH",
        requested_delta_weight: 0.01,
      });
    }
    return {
      agent_id: "autonomous_execution",
      execution_disposition: "ORDERS_ASSESSED",
      order_assessments: intents.map((intent, index) => ({
        assessment_local_id: `fake-execution-assessment-${index}`,
        order_intent_ref: intent.order_intent_ref,
        ts_code: intent.ts_code,
        requested_delta_weight: intent.requested_delta_weight,
        feasibility: "FEASIBLE",
        feasibility_confidence: 0.7,
        predicted_cost_bps: 5,
        max_executable_delta_weight: Math.abs(intent.requested_delta_weight),
        recommended_slice_count: 1,
        reason: "The fake liquidity snapshot permits the frozen intent.",
        claim_refs: [claimId],
      })),
      confidence: 0.6,
      claims,
      claim_refs: [claimId],
    };
  }
  const finalStage = schemaMentionsProperty(schema, "cro_control_resolutions");
  const positions = currentPositions(text);
  const targetPositions = positions.map(({ ticker, weight }, index) => ({
    position_local_id: `fake-position-${index}`,
    ts_code: ticker,
    target_weight: weight,
    position_decision: "HOLD",
    holding_period: "WEEKS",
    thesis_status: "INTACT",
    risk_flags: [],
    claim_refs: [claimId],
  }));
  const cashWeight = normalizedCashWeight(
    targetPositions.map((position) => position.target_weight),
  );
  const decision =
    targetPositions.length === 0
      ? {
          decision_disposition: "ALL_CASH" as const,
          target_positions: [],
          cash_weight: 1,
        }
      : {
          decision_disposition: "HOLD_CURRENT" as const,
          target_positions: targetPositions,
          cash_weight: cashWeight,
        };
  return {
    agent_id: "cio",
    decision_stage: finalStage ? "FINAL" : "PROPOSAL",
    ...decision,
    decision_reason: "Fake smoke preserves the complete frozen current portfolio.",
    ...(finalStage
      ? {
          cro_control_resolutions: frozenControlLocalRefs(text, "action_local_id").map(
            (localRef) => ({
              cro_action_local_ref: localRef,
              resolution: "COMPLIED",
              reason: "The final fake target complies with the accepted CRO action.",
              claim_refs: [claimId],
            }),
          ),
          execution_control_resolutions: frozenControlLocalRefs(text, "assessment_local_id").map(
            (localRef) => ({
              execution_assessment_local_ref: localRef,
              resolution: "COMPLIED",
              reason: "The final fake target complies with the accepted execution assessment.",
              claim_refs: [claimId],
            }),
          ),
        }
      : {}),
    confidence: 0.5,
    claims,
    claim_refs: [claimId],
    macro_input_attributions,
  };
}

function frozenCandidates(text: string): Array<{ candidate_ref: string; ts_code: string }> {
  return [
    ...new Map(
      [...text.matchAll(/candidate_ref=([^,\s]+),\s*ts_code=([^:\s]+):/g)].map((match) => [
        match[1] as string,
        { candidate_ref: match[1] as string, ts_code: match[2] as string },
      ]),
    ).values(),
  ];
}

function frozenOrderIntents(text: string): Array<{
  order_intent_ref: string;
  ts_code: string;
  requested_delta_weight: number;
}> {
  return [
    ...new Map(
      [
        ...text.matchAll(
          /order_intent_ref=([^,\s]+),\s*ts_code=([^,\s]+),\s*requested_delta_weight=(-?[0-9.]+)/g,
        ),
      ].map((match) => [
        match[1] as string,
        {
          order_intent_ref: match[1] as string,
          ts_code: match[2] as string,
          requested_delta_weight: Number(match[3]),
        },
      ]),
    ).values(),
  ];
}

function frozenControlLocalRefs(text: string, field: string): string[] {
  const expression = new RegExp(`"${field}":"([^"]+)"`, "g");
  return [...new Set([...text.matchAll(expression)].map((match) => match[1] as string))];
}

function normalizedCashWeight(weights: number[]): number {
  const cash = 1 - weights.reduce((sum, weight) => sum + weight, 0);
  return Math.abs(cash) < 1e-12 ? 0 : cash;
}

function fakeSuperinvestorSubmission(agent: string, messages: unknown): unknown {
  const evidenceId = firstEvidenceId(messageText(messages));
  const claimId = `fake-claim-${agent}`;
  return {
    agent,
    selection_status: "NO_QUALIFIED_CANDIDATES",
    confidence: 0.5,
    holding_period: "MONTHS",
    picks: [],
    key_drivers: [
      {
        driver_local_id: `fake-driver-${agent}`,
        summary: "The frozen candidate snapshot contains no qualified activation.",
        claim_refs: [claimId],
      },
    ],
    risks: [
      {
        risk_local_id: `fake-risk-${agent}`,
        summary: "Activating an unqualified candidate would exceed the evidence boundary.",
        claim_refs: [claimId],
      },
    ],
    claims: [
      {
        claim_id: claimId,
        claim_kind: "RISK_FLAG",
        statement: "Fake smoke found no evidence-supported Superinvestor candidate.",
        structured_conclusion: { selection_status: "NO_QUALIFIED_CANDIDATES" },
        evidence_ids: evidenceId ? [evidenceId] : [],
        research_rule_refs: [],
      },
    ],
    claim_refs: [claimId],
    macro_input_attributions: MACRO_AGENT_IDS.map((agentId) => ({
      agent_id: agentId,
      target_type: "SUBMISSION_SUMMARY",
      target_local_ref: "$SUBMISSION",
      claim_refs_used: [],
      effect: "NOT_MATERIAL",
    })),
  };
}

function fakeRelationshipSubmission(messages: unknown): unknown {
  const evidenceId = firstEvidenceId(messageText(messages));
  const claimId = "fake-claim-relationship_mapper";
  return {
    agent: "relationship_mapper",
    factual_edges: [],
    predictive_edges: [],
    predictive_graph_status: "NO_QUALIFIED_PREDICTIVE_EDGE",
    predictive_graph_abstention_confidence: 0.5,
    key_drivers: [
      {
        driver_local_id: "relationship-driver-1",
        summary: "Frozen opportunity evidence is insufficient for a predictive edge.",
        claim_refs: [claimId],
      },
    ],
    risks: [
      {
        risk_local_id: "relationship-risk-1",
        summary: "An unsubmitted candidate may still activate after the as-of time.",
        claim_refs: [claimId],
      },
    ],
    claims: [
      {
        claim_id: claimId,
        claim_kind: "RISK_FLAG",
        statement: "Fake smoke found no evidence-supported predictive relationship edge.",
        structured_conclusion: { predictive_graph_status: "NO_QUALIFIED_PREDICTIVE_EDGE" },
        evidence_ids: evidenceId ? [evidenceId] : [],
        research_rule_refs: [],
      },
    ],
    claim_refs: [claimId],
    macro_input_attributions: MACRO_AGENT_IDS.map((macroAgentId) => ({
      agent_id: macroAgentId,
      target_type: "SUBMISSION_SUMMARY",
      target_local_ref: "$SUBMISSION",
      claim_refs_used: [],
      effect: "NOT_MATERIAL",
    })),
  };
}

function fakeSectorDirectionResearch(name: StandardSectorAgentId, messages: unknown): unknown {
  const evidenceId = firstEvidenceId(messageText(messages));
  const claimId = `fake-claim-${name}`;
  const directions = STANDARD_SECTOR_ROLE_CONTRACTS[name].directionIds;
  const criterionResults = fakeSectorCriterionResults(name, claimId, evidenceId);
  if (directions.length === 1) {
    return {
      research_mode: "SINGLE_DIRECTION_QUALIFICATION",
      comparison_claims: [
        {
          claim_id: claimId,
          claim_kind: "FACT",
          statement: "Fake structural single-direction qualification.",
          structured_conclusion: { research_mode: "SINGLE_DIRECTION_QUALIFICATION" },
          evidence_ids: evidenceId ? [evidenceId] : [],
          research_rule_refs: [],
        },
      ],
      direction_comparisons: [],
      single_direction_qualification: {
        qualification_local_id: `qualification-${name}`,
        direction_id: directions[0],
        null_benchmark_contract_id: `single-null:${name}`,
        criterion_results: criterionResults,
        claim_refs: [claimId],
      },
    };
  }
  const comparisons: Array<Record<string, unknown>> = [];
  for (let i = 0; i < directions.length; i++) {
    for (let j = i + 1; j < directions.length; j++) {
      comparisons.push({
        comparison_local_id: `pair-${i}-${j}`,
        direction_a_id: directions[i],
        direction_b_id: directions[j],
        criterion_results: criterionResults,
        claim_refs: [claimId],
      });
    }
  }
  return {
    research_mode: "PAIRWISE",
    comparison_claims: [
      {
        claim_id: claimId,
        claim_kind: "FACT",
        statement: "Fake structural direction research.",
        structured_conclusion: { research_mode: "PAIRWISE" },
        evidence_ids: evidenceId ? [evidenceId] : [],
        research_rule_refs: [],
      },
    ],
    direction_comparisons: comparisons,
    single_direction_qualification: null,
  };
}

function fakeSectorCriterionResults(
  name: StandardSectorAgentId,
  claimId: string,
  evidenceId: string | null,
): Array<Record<string, unknown>> {
  return [
    ...["FUNDAMENTALS", "VALUATION", "BASKET_TECHNICALS", "RISK_ASYMMETRY"].map(
      (criterion, index) => ({
        criterion,
        comparison_status: "COMPARABLE",
        verdict: index < 2 ? "FAVORS_A" : "NEUTRAL",
        claim_refs: [claimId],
      }),
    ),
    {
      criterion: "MACRO_EVENT_FIT",
      coverage_state: "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT",
      comparison_status: "COMPARABLE",
      verdict: "NEUTRAL",
      claim_refs: [claimId],
      coverage_evidence_ids: [evidenceId ?? `fake-${name}-snapshot`],
    },
    {
      criterion: "CATALYSTS",
      coverage_state: "COVERAGE_CONFIRMED_NO_MATERIAL_CATALYST",
      comparison_status: "COMPARABLE",
      verdict: "NEUTRAL",
      claim_refs: [claimId],
      coverage_evidence_ids: [evidenceId ?? `fake-${name}-snapshot`],
    },
    ...["ETF_PRICE_CONFIRMATION", "ETF_SHARE_FLOW_CONFIRMATION"].map((criterion) => ({
      criterion,
      comparison_status: "INCOMPARABLE",
      verdict: "INCOMPARABLE",
      claim_refs: [],
    })),
  ];
}

function fakeSectorSubmission(
  name: StandardSectorAgentId,
  messages: unknown,
  selected: boolean,
): unknown {
  const evidenceId = firstEvidenceId(messageText(messages));
  const claimId = `fake-claim-${name}`;
  const directions = STANDARD_SECTOR_ROLE_CONTRACTS[name].directionIds;
  const singleDirection = directions.length === 1;
  const preferredLocalId = directions[0];
  const leastLocalId = directions[directions.length - 1];
  return {
    agent: name,
    selection_status: selected ? "SELECTED" : "NO_QUALIFIED_DIRECTION",
    preferred_direction: selected
      ? {
          selection_role: "PREFERRED",
          direction_local_id: preferredLocalId,
          direction_id: directions[0],
          allocation_action: "OVERWEIGHT",
          strength: 2,
          thesis: "Fake preferred direction selected by the frozen comparison matrix.",
          claim_refs: [claimId],
        }
      : { status: "NO_QUALIFIED_DIRECTION" },
    least_preferred_direction:
      selected && !singleDirection
        ? {
            selection_role: "LEAST_PREFERRED",
            direction_local_id: leastLocalId,
            direction_id: directions[directions.length - 1],
            allocation_action: "UNDERWEIGHT",
            strength: 2,
            thesis: "Fake least-preferred direction selected by the frozen comparison matrix.",
            claim_refs: [claimId],
          }
        : selected && singleDirection
          ? {
              status: "NO_QUALIFIED_AVOID_DIRECTION",
              reason: "SINGLE_ELIGIBLE_DIRECTION",
            }
          : {
              status: "NO_QUALIFIED_AVOID_DIRECTION",
              reason: "PREFERRED_NOT_QUALIFIED",
            },
    persistence_horizon: "DAYS",
    confidence: 0.4,
    key_drivers: [{ driver_local_id: "driver-1", summary: "Fake driver", claim_refs: [claimId] }],
    risks: [{ risk_local_id: "risk-1", summary: "Fake risk", claim_refs: [claimId] }],
    claims: [
      {
        claim_id: claimId,
        claim_kind: selected ? "FACT" : "RISK_FLAG",
        statement: "Fake structural sector final selection.",
        structured_conclusion: {
          conclusion_type: selected ? "SECTOR_DIRECTION" : "SECTOR_ABSTENTION",
          target_local_ref: selected ? preferredLocalId : null,
          selection_status: selected ? "SELECTED" : "NO_QUALIFIED_DIRECTION",
          direction_id: selected ? directions[0] : null,
          position_action: null,
          summary: "Fake structural sector final selection.",
        },
        evidence_ids: evidenceId ? [evidenceId] : [],
        research_rule_refs: [],
      },
    ],
    claim_refs: [claimId],
    preferred_security_status: "NO_QUALIFIED_SECURITY",
    preferred_security_abstention_confidence: selected ? 0.5 : null,
    long_picks: [],
    least_preferred_security_status:
      selected && !singleDirection ? "NO_QUALIFIED_SECURITY" : "NOT_APPLICABLE",
    least_preferred_security_abstention_confidence: selected && !singleDirection ? 0.5 : null,
    short_or_avoid_picks: [],
    macro_input_attributions: MACRO_AGENT_IDS.map((macroAgentId) => ({
      agent_id: macroAgentId,
      target_type: "SUBMISSION_SUMMARY",
      target_local_ref: "$SUBMISSION",
      claim_refs_used: [],
      effect: "NOT_MATERIAL",
    })),
  };
}

function fakeMacroSubmission(name: MacroAgentId, messages: unknown): unknown {
  const evidenceId = firstEvidenceId(messageText(messages));
  const claimId = `fake-claim-${name}`;
  const claims = [
    {
      claim_id: claimId,
      claim_kind: "RISK_FLAG",
      statement: "Fake smoke found no evidence-supported directional conclusion.",
      structured_conclusion: {
        conclusion_type: "MACRO_RISK",
        subject: name,
        state: "No evidence-supported directional conclusion",
        a_share_transmission: "No evidence-supported A-share transmission",
      },
      evidence_ids: evidenceId ? [evidenceId] : [],
      research_rule_refs: [],
    },
  ];
  const signal = {
    direction: "NEUTRAL",
    strength: 0,
    persistence_horizon: "DAYS",
    evaluation_horizon_trading_days: 5,
    confidence: 0.4,
    channels: ["insufficient directional evidence"],
    claim_refs: [claimId],
  };
  const contract = MACRO_ROLE_CONTRACTS[name];
  return contract.mode === "DIRECT"
    ? { mode: "DIRECT", claims, key_drivers: ["fake structural smoke"], signal }
    : {
        mode: "COMPONENTS",
        claims,
        key_drivers: ["fake structural smoke"],
        components: Object.keys(contract.components)
          .sort()
          .map((component) => ({ component, ...signal })),
      };
}

export function fakeContractOutput(
  authored: Record<string, unknown>,
  name: string,
  messages: unknown,
): Record<string, unknown> {
  const output = structuredClone(authored);
  const claimId = `fake-claim-${name}`;
  const evidenceId = firstEvidenceId(messageText(messages));
  const nonEmpty = (field: string) => Array.isArray(output[field]) && output[field].length > 0;
  if (
    ["semiconductor", "energy", "biotech", "consumer", "industrials", "financials"].includes(name)
  ) {
    output.selection_disposition =
      nonEmpty("longs") || nonEmpty("shorts") ? "CANDIDATES" : "NO_QUALIFIED_CANDIDATES";
  }
  if (["druckemiller", "druckenmiller", "munger", "burry", "ackman"].includes(name)) {
    output.selection_status = nonEmpty("picks") ? "SELECTED" : "NO_QUALIFIED_CANDIDATES";
  }
  if (name === "cro") {
    output.review_disposition =
      nonEmpty("rejected_picks") || nonEmpty("required_adjustments")
        ? "REVIEW_ACTIONS"
        : "NO_OBJECTION";
  }
  if (name === "alpha_discovery") {
    output.discovery_disposition = nonEmpty("novel_picks") ? "CANDIDATES" : "NONE_FOUND";
  }
  if (name === "autonomous_execution") {
    output.execution_disposition = nonEmpty("trades") ? "TRADES" : "NO_DELTA";
  }
  const explicitEmpty = [
    "NO_QUALIFIED_CANDIDATES",
    "NO_OBJECTION",
    "NONE_FOUND",
    "NO_DELTA",
    "BLOCKED",
  ].some((value) => Object.values(output).includes(value));
  output.claims = [
    evidenceId && !explicitEmpty
      ? {
          claim_id: claimId,
          claim_kind: "FACT",
          statement: "Fake authored output is bound to current runtime evidence.",
          structured_conclusion: { disposition: dispositionOf(output) },
          evidence_ids: [evidenceId],
          research_rule_refs: [],
        }
      : {
          claim_id: claimId,
          claim_kind: "RISK_FLAG",
          statement: "Fake authored output has no evidence-supported actionable conclusion.",
          structured_conclusion: { disposition: dispositionOf(output) },
          evidence_ids: evidenceId ? [evidenceId] : [],
          research_rule_refs: [],
        },
  ];
  output.claim_refs = [claimId];
  if (name === "cio") output.decision_claim_refs = [claimId];
  attachEntryClaimRefs(output, claimId);
  return output;
}

export function fakeSchemaValue(schema: unknown): Record<string, unknown> {
  const value = synthesize(normalizeJsonSchema(schema));
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function normalizeJsonSchema(schema: unknown): unknown {
  if (schema !== null && typeof schema === "object" && !Array.isArray(schema)) {
    const record = schema as Record<string, unknown>;
    if (
      !("def" in record || "_def" in record) &&
      (typeof record.$schema === "string" ||
        typeof record.type === "string" ||
        "properties" in record ||
        "oneOf" in record ||
        "anyOf" in record ||
        "allOf" in record ||
        "$ref" in record)
    ) {
      return schema;
    }
  }
  return z.toJSONSchema(schema as z.ZodType);
}

function schemaMentionsProperty(schema: unknown, property: string): boolean {
  if (schema === null || typeof schema !== "object") return false;
  if (Array.isArray(schema)) return schema.some((entry) => schemaMentionsProperty(entry, property));
  const record = schema as Record<string, unknown>;
  const properties = record.properties;
  if (
    properties &&
    typeof properties === "object" &&
    !Array.isArray(properties) &&
    property in properties
  ) {
    return true;
  }
  return Object.values(record).some((entry) => schemaMentionsProperty(entry, property));
}

function schemaMentionsConst(schema: unknown, value: string): boolean {
  if (schema === null || typeof schema !== "object") return false;
  if (Array.isArray(schema)) return schema.some((entry) => schemaMentionsConst(entry, value));
  const record = schema as Record<string, unknown>;
  if (record.const === value) return true;
  return Object.values(record).some((entry) => schemaMentionsConst(entry, value));
}

function synthesize(schema: unknown): unknown {
  if (schema === null || typeof schema !== "object" || Array.isArray(schema)) return null;
  const record = schema as Record<string, unknown>;
  if ("const" in record) return record.const;
  if (Array.isArray(record.enum) && record.enum.length > 0) return record.enum[0];
  if (Array.isArray(record.anyOf)) {
    const branch = record.anyOf.find(
      (item) =>
        !(item && typeof item === "object" && (item as Record<string, unknown>).type === "null"),
    );
    return synthesize(branch);
  }
  if (record.type === "object" || record.properties) {
    const properties = (record.properties ?? {}) as Record<string, unknown>;
    const required = new Set((record.required as string[] | undefined) ?? []);
    return Object.fromEntries(
      Object.entries(properties)
        .filter(([key]) => required.has(key))
        .map(([key, value]) => [key, synthesize(value)]),
    );
  }
  if (record.type === "array") {
    const count = typeof record.minItems === "number" ? record.minItems : 0;
    return Array.from({ length: count }, () => synthesize(record.items));
  }
  if (record.type === "number" || record.type === "integer") {
    const minimum = typeof record.minimum === "number" ? record.minimum : 0;
    const maximum = typeof record.maximum === "number" ? record.maximum : Number.POSITIVE_INFINITY;
    return Math.min(Math.max(0, minimum), maximum);
  }
  if (record.type === "boolean") return false;
  return "fake";
}

function configureDisposition(
  output: Record<string, unknown>,
  positions: Array<{ ticker: string; weight: number }>,
  claimId: string,
): boolean {
  if ("selection_disposition" in output) {
    output.selection_disposition = "NO_QUALIFIED_CANDIDATES";
    output.longs = [];
    output.shorts = [];
    output.picks = [];
    return true;
  }
  if ("review_disposition" in output) {
    output.review_disposition = "NO_OBJECTION";
    output.rejected_picks = [];
    output.required_adjustments = [];
    return true;
  }
  if ("discovery_disposition" in output) {
    output.discovery_disposition = "NONE_FOUND";
    output.novel_picks = [];
    return true;
  }
  if ("execution_disposition" in output) {
    output.execution_disposition = "NO_DELTA";
    output.trades = [];
    output.execution_checks = [];
    return true;
  }
  if ("decision_disposition" in output) {
    output.decision_reason =
      positions.length === 0
        ? "No current positions and no evidence-supported target."
        : "Preserve every current position in the fake smoke run.";
    output.dissent_refs = [];
    if (positions.length === 0) {
      output.decision_disposition = "ALL_CASH";
      output.portfolio_actions = [];
      output.position_reviews = [];
      return false;
    }
    output.decision_disposition = "HOLD_CURRENT";
    output.portfolio_actions = positions.map(({ ticker, weight }) => ({
      ticker,
      action: "HOLD",
      position_decision: "HOLD",
      current_weight: weight,
      target_weight: weight,
      delta_weight: 0,
      holding_period: "1M",
      position_decision_reason: "Fake smoke preserves current exposure.",
      thesis_status: "intact",
      risk_flags: [],
      dissent_notes: "",
      claim_refs: [claimId],
    }));
    output.position_reviews = positions.map(({ ticker, weight }) => ({
      ticker,
      decision: "HOLD",
      target_weight: weight,
      reason: "Fake smoke preserves current exposure.",
      thesis_status: "intact",
      risk_flags: [],
      confidence: 0,
      claim_refs: [claimId],
    }));
  }
  return false;
}

function attachEntryClaimRefs(output: Record<string, unknown>, claimId: string): void {
  for (const field of [
    "longs",
    "shorts",
    "picks",
    "rejected_picks",
    "required_adjustments",
    "novel_picks",
    "trades",
    "execution_checks",
    "portfolio_actions",
    "position_reviews",
  ]) {
    if (!Array.isArray(output[field])) continue;
    output[field] = output[field].map((entry) =>
      entry !== null && typeof entry === "object"
        ? { ...(entry as Record<string, unknown>), claim_refs: [claimId] }
        : entry,
    );
  }
}

function currentPositions(text: string): Array<{ ticker: string; weight: number }> {
  return [...text.matchAll(/^\*\s+([0-9A-Z.]+): weight=([0-9.]+)/gm)].map((match) => ({
    ticker: match[1] as string,
    weight: Number(match[2]),
  }));
}

function firstEvidenceId(text: string): string | null {
  const marker = "Runtime-owned evidence catalog (use only these evidence_id values):";
  const markerIndex = text.indexOf(marker);
  if (markerIndex >= 0) {
    try {
      const catalog = JSON.parse(text.slice(markerIndex + marker.length).trim()) as {
        evidence?: Array<{ evidence_id?: unknown; freshness?: unknown }>;
      };
      const current = catalog.evidence?.find(
        (entry) => entry.freshness === "current" && typeof entry.evidence_id === "string",
      );
      if (typeof current?.evidence_id === "string") return current.evidence_id;
      const first = catalog.evidence?.find((entry) => typeof entry.evidence_id === "string");
      if (typeof first?.evidence_id === "string") return first.evidence_id;
    } catch {
      // Repair prompts JSON-escape the immutable original task; use the scan below.
    }
  }
  for (const match of text.matchAll(
    /"evidence_id"\s*:\s*"([^"]+)"[\s\S]{0,1200}?"freshness"\s*:\s*"current"/g,
  )) {
    if (match[1]) return match[1];
  }
  const anyEvidence = text.match(/"evidence_id"\s*:\s*"([^"]+)"/);
  if (anyEvidence?.[1]) return anyEvidence[1];
  return null;
}

function dispositionOf(output: Record<string, unknown>): unknown {
  return (
    output.selection_status ??
    output.selection_disposition ??
    output.review_disposition ??
    output.discovery_disposition ??
    output.execution_disposition ??
    output.decision_disposition ??
    "ANALYSIS"
  );
}

function messageText(messages: unknown): string {
  if (!Array.isArray(messages)) return String(messages ?? "");
  return (messages as BaseMessage[])
    .map((message) =>
      typeof message.content === "string" ? message.content : JSON.stringify(message.content),
    )
    .join("\n");
}
