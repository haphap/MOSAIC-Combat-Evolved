import {
  adaptMacroAttributionProviderJsonSchema,
  normalizeMacroAttributionProviderPayload,
} from "./macro_attribution.js";
import {
  adaptSectorDirectionProviderJsonSchema,
  normalizeSectorDirectionProviderPayload,
} from "./sector_direction_provider_adapter.js";

const STANDARD_SECTOR_AGENTS = new Set([
  "semiconductor",
  "technology",
  "energy",
  "biotech",
  "consumer",
  "industrials",
  "real_estate_construction",
  "financials",
  "agriculture",
]);

const COMPACT_SELECTED_SECTOR = "SECTOR_SELECTED_COMPACT_V1";
const COMPACT_RELATIONSHIP_MAPPER = "RELATIONSHIP_MAPPER_COMPACT_V1";
const COMPACT_SUPERINVESTOR_ABSTENTION = "SUPERINVESTOR_ABSTENTION_COMPACT_V1";
const SUPERINVESTOR_AGENTS = new Set(["druckenmiller", "munger", "burry", "ackman"]);

export const SECTOR_ABSTENTION_PROVIDER_INSTRUCTION =
  "When the runtime directive is NO_QUALIFIED_DIRECTION, the bounded provider extraction " +
  "shape requests agent, least_preferred_reason, persistence_horizon, confidence, " +
  "abstention_summary, evidence_id, and macro_input_attributions. The runtime deterministically " +
  "materializes the required local RISK_FLAG claim, driver, risk, and empty security legs.";

export const SECTOR_SELECTED_PROVIDER_INSTRUCTION =
  "When the bounded provider extraction contract is SECTOR_SELECTED_COMPACT_V1, return the exact " +
  "runtime-owned direction ids, concise preferred/least theses, one driver, one risk, one accepted " +
  "evidence_id, security-leg decisions, and Macro attributions. Runtime deterministically assigns " +
  "local ids and expands the repetitive claim/reference envelope without changing your direction, " +
  "strength, confidence, security, or Macro-attribution judgments.";

export const SUPERINVESTOR_ABSTENTION_PROVIDER_INSTRUCTION =
  "When the bounded extraction contract is SUPERINVESTOR_ABSTENTION_COMPACT_V1, provide one " +
  "abstention summary, one risk summary, accepted evidence/rule ids, confidence, holding period, " +
  "and Macro attributions. Runtime deterministically expands the empty-candidate claim and closes " +
  "all local references; do not invent local claim ids.";

export const RELATIONSHIP_MAPPER_PROVIDER_INSTRUCTION =
  "The bounded extraction contract is RELATIONSHIP_MAPPER_COMPACT_V1. Return only the compact " +
  "fields requested by that schema: frozen factual edges, the predictive graph decision, at most " +
  "the listed frozen predictive candidates, one driver, one risk, accepted evidence/rule ids, and " +
  "Macro attributions. Do not emit claims, claim_refs, edge_local_id, or the canonical graph " +
  "envelope; runtime deterministically creates those fields after extraction.";

export function adaptStrictProviderJsonSchema(value: unknown): unknown {
  return adaptMacroAttributionProviderJsonSchema(
    adaptSectorFinalJsonSchema(adaptSectorDirectionProviderJsonSchema(value)),
  );
}

export function normalizeStrictProviderPayload(value: unknown): unknown {
  return normalizeMacroConclusionText(
    normalizeMacroAttributionProviderPayload(
      normalizeSectorFinalPayload(normalizeSectorDirectionProviderPayload(value)),
    ),
  );
}

function normalizeMacroConclusionText(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalizeMacroConclusionText);
  if (value === null || typeof value !== "object") return value;
  const record = value as Record<string, unknown>;
  if (typeof record.conclusion_type === "string" && record.conclusion_type.startsWith("MACRO_")) {
    return Object.fromEntries(
      Object.entries(record).map(([key, nested]) => [
        key,
        ["subject", "state", "a_share_transmission"].includes(key) && typeof nested === "string"
          ? nonNumericConclusionText(nested)
          : normalizeMacroConclusionText(nested),
      ]),
    );
  }
  return Object.fromEntries(
    Object.entries(record).map(([key, nested]) => [key, normalizeMacroConclusionText(nested)]),
  );
}

function nonNumericConclusionText(value: string): string {
  return (
    value
      .replace(/[+-]?\d+(?:\.\d+)?%?/g, "")
      .replace(/\s{2,}/g, " ")
      .trim() || "NON_NUMERIC_CONCLUSION"
  );
}

function adaptSectorFinalJsonSchema(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(adaptSectorFinalJsonSchema);
  if (value === null || typeof value !== "object") return value;
  const record = value as Record<string, unknown>;
  const relationshipUnion = relationshipUnionProviderSchema(record.oneOf);
  if (relationshipUnion) return relationshipUnion;
  const properties = objectRecord(record.properties);
  const agent = schemaConst(properties?.agent);
  const relationship = relationshipProviderSchema(properties, agent);
  if (relationship) return relationship;
  const superinvestorAbstention = superinvestorAbstentionProviderSchema(properties, agent);
  if (superinvestorAbstention) return superinvestorAbstention;
  const selected = selectedSectorProviderSchema(properties, agent);
  if (selected) return selected;
  if (
    properties &&
    agent &&
    STANDARD_SECTOR_AGENTS.has(agent) &&
    schemaConst(properties.selection_status) === "NO_QUALIFIED_DIRECTION"
  ) {
    const leastPreferred = objectRecord(properties.least_preferred_direction);
    const leastProperties = objectRecord(leastPreferred?.properties);
    if (!leastProperties?.reason || !properties.macro_input_attributions) return value;
    return {
      type: "object",
      properties: {
        agent: properties.agent,
        least_preferred_reason: leastProperties.reason,
        persistence_horizon: properties.persistence_horizon,
        confidence: properties.confidence,
        abstention_summary: { type: "string", minLength: 1, maxLength: 160 },
        evidence_id: runtimeEvidenceIdProviderSchema(),
        macro_input_attributions: {
          ...objectRecord(properties.macro_input_attributions),
          "x-mosaic-no-target-rows": true,
        },
      },
      required: [
        "agent",
        "least_preferred_reason",
        "persistence_horizon",
        "confidence",
        "abstention_summary",
        "evidence_id",
        "macro_input_attributions",
      ],
      additionalProperties: false,
    };
  }
  return Object.fromEntries(
    Object.entries(record).map(([key, nested]) => [key, adaptSectorFinalJsonSchema(nested)]),
  );
}

function relationshipUnionProviderSchema(value: unknown): Record<string, unknown> | null {
  if (!Array.isArray(value) || value.length !== 2) return null;
  const branches = value.flatMap((branch) => {
    const properties = objectRecord(objectRecord(branch)?.properties);
    return properties && schemaConst(properties.agent) === "relationship_mapper"
      ? [{ properties, status: schemaConst(properties.predictive_graph_status) }]
      : [];
  });
  const edgesBranch = branches.find((branch) => branch.status === "EDGES_PRESENT");
  const abstentionBranch = branches.find(
    (branch) => branch.status === "NO_QUALIFIED_PREDICTIVE_EDGE",
  );
  if (!edgesBranch || !abstentionBranch) return null;
  const factualCapacity = boundedArrayCapacity(edgesBranch.properties.factual_edges);
  const predictiveCapacity = boundedArrayCapacity(edgesBranch.properties.predictive_edges);
  const factualItems = objectRecord(objectRecord(edgesBranch.properties.factual_edges)?.items);
  if (
    factualCapacity === null ||
    predictiveCapacity === null ||
    !factualItems ||
    !edgesBranch.properties.macro_input_attributions
  ) {
    return null;
  }
  const properties: Record<string, unknown> = {
    provider_contract: { type: "string", const: COMPACT_RELATIONSHIP_MAPPER },
    agent: edgesBranch.properties.agent,
    factual_edges: {
      type: "array",
      items: compactRelationshipFactualItems(factualItems),
      maxItems: factualCapacity,
    },
    predictive_graph_status: {
      type: "string",
      enum: ["EDGES_PRESENT", "NO_QUALIFIED_PREDICTIVE_EDGE"],
    },
    predictive_edges: {
      type: "array",
      items: compactRelationshipPredictiveItems(edgesBranch.properties.predictive_edges),
      maxItems: predictiveCapacity,
    },
    predictive_graph_abstention_confidence: {
      type: "number",
      minimum: 0,
      maximum: 1,
    },
    driver_summary: conciseProviderText(),
    risk_summary: conciseProviderText(),
    evidence_id: runtimeEvidenceIdProviderSchema(),
    research_rule_ref: { type: "string", minLength: 1, maxLength: 256 },
    macro_input_attributions: edgesBranch.properties.macro_input_attributions,
  };
  return {
    type: "object",
    properties,
    required: Object.keys(properties),
    additionalProperties: false,
  };
}

function normalizeSectorFinalPayload(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalizeSectorFinalPayload);
  if (value === null || typeof value !== "object") return value;
  const record = value as Record<string, unknown>;
  if (record.provider_contract === COMPACT_RELATIONSHIP_MAPPER) {
    return materializeRelationshipMapper(record);
  }
  if (record.provider_contract === COMPACT_SUPERINVESTOR_ABSTENTION) {
    return materializeSuperinvestorAbstention(record);
  }
  if (record.provider_contract === COMPACT_SELECTED_SECTOR) {
    return materializeSelectedSector(record);
  }
  if (isSectorAbstentionProviderPayload(record)) {
    const agent = record.agent as string;
    const summary = record.abstention_summary as string;
    const claimId = `provider-${agent}-abstention-claim`;
    return {
      agent,
      selection_status: "NO_QUALIFIED_DIRECTION",
      preferred_direction: { status: "NO_QUALIFIED_DIRECTION" },
      least_preferred_direction: {
        status: "NO_QUALIFIED_AVOID_DIRECTION",
        reason: record.least_preferred_reason,
      },
      persistence_horizon: record.persistence_horizon,
      confidence: record.confidence,
      key_drivers: [
        {
          driver_local_id: `provider-${agent}-abstention-driver`,
          summary,
          claim_refs: [claimId],
        },
      ],
      risks: [
        {
          risk_local_id: `provider-${agent}-abstention-risk`,
          summary,
          claim_refs: [claimId],
        },
      ],
      claims: [
        {
          claim_id: claimId,
          claim_kind: "RISK_FLAG",
          statement: summary,
          structured_conclusion: {
            conclusion_type: "SECTOR_ABSTENTION",
            target_local_ref: null,
            selection_status: "NO_QUALIFIED_DIRECTION",
            direction_id: null,
            position_action: null,
            summary,
          },
          evidence_ids: [record.evidence_id],
          research_rule_refs: [],
        },
      ],
      claim_refs: [claimId],
      macro_input_attributions: record.macro_input_attributions,
      preferred_security_status: "NO_QUALIFIED_SECURITY",
      preferred_security_abstention_confidence: null,
      long_picks: [],
      least_preferred_security_status: "NOT_APPLICABLE",
      least_preferred_security_abstention_confidence: null,
      short_or_avoid_picks: [],
    };
  }
  return Object.fromEntries(
    Object.entries(record).map(([key, nested]) => [key, normalizeSectorFinalPayload(nested)]),
  );
}

function superinvestorAbstentionProviderSchema(
  properties: Record<string, unknown> | null,
  agent: string | null,
): Record<string, unknown> | null {
  if (
    !properties ||
    !agent ||
    !SUPERINVESTOR_AGENTS.has(agent) ||
    schemaConst(properties.selection_status) !== "NO_QUALIFIED_CANDIDATES" ||
    !properties.confidence ||
    !properties.holding_period ||
    !properties.macro_input_attributions
  ) {
    return null;
  }
  const compactProperties = {
    provider_contract: { type: "string", const: COMPACT_SUPERINVESTOR_ABSTENTION },
    agent: properties.agent,
    confidence: properties.confidence,
    holding_period: properties.holding_period,
    abstention_summary: conciseProviderText(),
    risk_summary: conciseProviderText(),
    evidence_id: runtimeEvidenceIdProviderSchema(),
    research_rule_ref: { type: "string", minLength: 1, maxLength: 256 },
    macro_input_attributions: properties.macro_input_attributions,
  };
  return {
    type: "object",
    properties: compactProperties,
    required: Object.keys(compactProperties),
    additionalProperties: false,
  };
}

function materializeSuperinvestorAbstention(input: Record<string, unknown>): unknown {
  const agent = String(input.agent);
  const claimId = `provider-${agent}-abstention-claim`.slice(0, 128);
  const claimRefs = [claimId];
  const summary = String(input.abstention_summary);
  return {
    agent,
    selection_status: "NO_QUALIFIED_CANDIDATES",
    confidence: input.confidence,
    holding_period: input.holding_period,
    key_drivers: [
      {
        driver_local_id: `provider-${agent}-abstention-driver`.slice(0, 128),
        summary,
        claim_refs: claimRefs,
      },
    ],
    risks: [
      {
        risk_local_id: `provider-${agent}-abstention-risk`.slice(0, 128),
        summary: input.risk_summary,
        claim_refs: claimRefs,
      },
    ],
    claims: [
      {
        claim_id: claimId,
        claim_kind: "INTERPRETATION",
        statement: summary,
        structured_conclusion: {
          conclusion_type: "POSITION_DECISION",
          subject: "FROZEN_CANDIDATE_UNIVERSE",
          state: "NO_QUALIFIED_CANDIDATES",
        },
        evidence_ids: [input.evidence_id],
        research_rule_refs: [input.research_rule_ref],
      },
    ],
    claim_refs: claimRefs,
    macro_input_attributions: input.macro_input_attributions,
    picks: [],
  };
}

function relationshipProviderSchema(
  properties: Record<string, unknown> | null,
  agent: string | null,
): Record<string, unknown> | null {
  if (!properties || agent !== "relationship_mapper") return null;
  const status = schemaConst(properties.predictive_graph_status);
  const factualCapacity = boundedArrayCapacity(properties.factual_edges);
  const predictiveCapacity = boundedArrayCapacity(properties.predictive_edges);
  const factualItems = objectRecord(objectRecord(properties.factual_edges)?.items);
  if (
    !status ||
    factualCapacity === null ||
    predictiveCapacity === null ||
    !factualItems ||
    !properties.macro_input_attributions
  ) {
    return null;
  }
  const compactProperties: Record<string, unknown> = {
    provider_contract: { type: "string", const: COMPACT_RELATIONSHIP_MAPPER },
    agent: properties.agent,
    factual_edges: {
      type: "array",
      items: compactRelationshipFactualItems(factualItems),
      maxItems: factualCapacity,
    },
    predictive_graph_status: properties.predictive_graph_status,
    ...(status === "EDGES_PRESENT"
      ? {
          predictive_edges: {
            type: "array",
            items: compactRelationshipPredictiveItems(properties.predictive_edges),
            minItems: 1,
            maxItems: predictiveCapacity,
          },
        }
      : {
          predictive_graph_abstention_confidence: properties.predictive_graph_abstention_confidence,
        }),
    driver_summary: conciseProviderText(),
    risk_summary: conciseProviderText(),
    evidence_id: runtimeEvidenceIdProviderSchema(),
    research_rule_ref: { type: "string", minLength: 1, maxLength: 256 },
    macro_input_attributions: properties.macro_input_attributions,
  };
  return {
    type: "object",
    properties: compactProperties,
    required: Object.keys(compactProperties),
    additionalProperties: false,
  };
}

function compactRelationshipPredictiveItems(value: unknown): unknown {
  const items = objectRecord(objectRecord(value)?.items);
  if (!items) return {};
  if (Array.isArray(items.anyOf)) {
    return {
      anyOf: items.anyOf.map((schema) =>
        compactRelationshipEdgeSchema(objectRecord(schema), [
          "edge_candidate_id",
          "source_entity",
          "target_entity",
          "edge_type",
          "transmission_direction",
          "activation_trigger",
          "evaluation_horizon_trading_days",
          "model_confidence",
        ]),
      ),
    };
  }
  return compactRelationshipEdgeSchema(items, [
    "edge_candidate_id",
    "source_entity",
    "target_entity",
    "edge_type",
    "transmission_direction",
    "activation_trigger",
    "evaluation_horizon_trading_days",
    "model_confidence",
  ]);
}

function compactRelationshipFactualItems(items: Record<string, unknown>): unknown {
  const keys = ["source_entity", "target_entity", "edge_type"];
  if (Array.isArray(items.anyOf)) {
    return {
      anyOf: items.anyOf.map((schema) => compactRelationshipEdgeSchema(objectRecord(schema), keys)),
    };
  }
  return compactRelationshipEdgeSchema(items, keys);
}

function compactRelationshipEdgeSchema(
  schema: Record<string, unknown> | null,
  keys: string[],
): Record<string, unknown> {
  const sourceProperties = objectRecord(schema?.properties) ?? {};
  const properties = Object.fromEntries(
    keys.flatMap((key) => (sourceProperties[key] ? [[key, sourceProperties[key]]] : [])),
  );
  return {
    type: "object",
    properties,
    required: Object.keys(properties),
    additionalProperties: false,
  };
}

function materializeRelationshipMapper(input: Record<string, unknown>): unknown {
  const claimId = "provider-relationship-mapper-claim";
  const claimRefs = [claimId];
  const factualRows = Array.isArray(input.factual_edges) ? input.factual_edges : [];
  const predictiveRows = Array.isArray(input.predictive_edges) ? input.predictive_edges : [];
  const status = input.predictive_graph_status;
  return {
    agent: "relationship_mapper",
    factual_edges: factualRows.flatMap((value, index) => {
      const row = objectRecord(value);
      return row
        ? [
            {
              edge_local_id: `provider-factual-edge-${index + 1}`,
              ...row,
              claim_refs: claimRefs,
            },
          ]
        : [];
    }),
    key_drivers: [
      {
        driver_local_id: "provider-relationship-driver",
        summary: input.driver_summary,
        claim_refs: claimRefs,
      },
    ],
    risks: [
      {
        risk_local_id: "provider-relationship-risk",
        summary: input.risk_summary,
        claim_refs: claimRefs,
      },
    ],
    claims: [
      {
        claim_id: claimId,
        claim_kind: "INTERPRETATION",
        statement: input.driver_summary,
        structured_conclusion: {
          conclusion_type: "RELATIONSHIP_GRAPH",
          state: status,
        },
        evidence_ids: [input.evidence_id],
        research_rule_refs: [input.research_rule_ref],
      },
    ],
    claim_refs: claimRefs,
    macro_input_attributions: input.macro_input_attributions,
    predictive_graph_status: status,
    predictive_edges:
      status === "EDGES_PRESENT"
        ? predictiveRows.flatMap((value, index) => {
            const row = objectRecord(value);
            return row
              ? [
                  {
                    edge_local_id: `provider-predictive-edge-${index + 1}`,
                    ...row,
                    claim_refs: claimRefs,
                  },
                ]
              : [];
          })
        : [],
    predictive_graph_abstention_confidence:
      status === "EDGES_PRESENT" ? null : input.predictive_graph_abstention_confidence,
  };
}

function selectedSectorProviderSchema(
  properties: Record<string, unknown> | null,
  agent: string | null,
): Record<string, unknown> | null {
  if (
    !properties ||
    !agent ||
    !STANDARD_SECTOR_AGENTS.has(agent) ||
    schemaConst(properties.selection_status) !== "SELECTED"
  ) {
    return null;
  }
  const preferred = objectRecord(properties.preferred_direction);
  const preferredProperties = objectRecord(preferred?.properties);
  const preferredDirectionId = schemaConst(preferredProperties?.direction_id);
  const preferredDirectionLocalId = schemaConst(preferredProperties?.direction_local_id);
  const least = objectRecord(properties.least_preferred_direction);
  const leastProperties = objectRecord(least?.properties);
  const leastDirectionId = schemaConst(leastProperties?.direction_id);
  const leastDirectionLocalId = schemaConst(leastProperties?.direction_local_id);
  const leastReason = schemaConst(leastProperties?.reason);
  if (
    !preferredDirectionId ||
    !preferredDirectionLocalId ||
    (!leastDirectionId && !leastReason) ||
    !preferredProperties?.strength ||
    !properties.persistence_horizon ||
    !properties.confidence ||
    !properties.macro_input_attributions
  ) {
    return null;
  }
  const preferredCapacity = arrayCapacity(properties.long_picks);
  const leastCapacity = arrayCapacity(properties.short_or_avoid_picks);
  const compactProperties: Record<string, unknown> = {
    provider_contract: { type: "string", const: COMPACT_SELECTED_SECTOR },
    agent: properties.agent,
    preferred_direction_id: preferredProperties.direction_id,
    preferred_direction_local_id: preferredProperties.direction_local_id,
    preferred_strength: preferredProperties.strength,
    preferred_thesis: conciseProviderText(),
    ...(leastDirectionId && leastDirectionLocalId
      ? {
          least_preferred_direction_id: leastProperties?.direction_id,
          least_preferred_direction_local_id: leastProperties?.direction_local_id,
          least_preferred_strength: leastProperties?.strength,
          least_preferred_thesis: conciseProviderText(),
        }
      : { least_preferred_reason: leastProperties?.reason }),
    persistence_horizon: properties.persistence_horizon,
    confidence: properties.confidence,
    driver_summary: conciseProviderText(),
    risk_summary: conciseProviderText(),
    evidence_id: runtimeEvidenceIdProviderSchema(),
    research_rule_ref: { type: "string", minLength: 1, maxLength: 256 },
    preferred_security: compactSecurityLegSchema(preferredCapacity, false),
    least_preferred_security: leastDirectionId
      ? compactSecurityLegSchema(leastCapacity, false)
      : compactSecurityLegSchema(0, true),
    macro_input_attributions: properties.macro_input_attributions,
  };
  return {
    type: "object",
    properties: compactProperties,
    required: Object.keys(compactProperties),
    additionalProperties: false,
  };
}

function compactSecurityLegSchema(
  capacity: number,
  notApplicable: boolean,
): Record<string, unknown> {
  if (notApplicable) {
    return {
      type: "object",
      properties: { status: { type: "string", const: "NOT_APPLICABLE" } },
      required: ["status"],
      additionalProperties: false,
    };
  }
  const noQualified = {
    type: "object",
    properties: {
      status: { type: "string", const: "NO_QUALIFIED_SECURITY" },
      abstention_confidence: { type: "number", minimum: 0, maximum: 1 },
    },
    required: ["status", "abstention_confidence"],
    additionalProperties: false,
  };
  if (capacity === 0) return noQualified;
  return {
    anyOf: [
      {
        type: "object",
        properties: {
          status: { type: "string", const: "PICKS_PRESENT" },
          picks: {
            type: "array",
            items: compactSecurityPickSchema(),
            minItems: 1,
            maxItems: capacity,
          },
        },
        required: ["status", "picks"],
        additionalProperties: false,
      },
      noQualified,
    ],
  };
}

function compactSecurityPickSchema(): Record<string, unknown> {
  const properties = {
    ts_code: { type: "string", pattern: "^\\d{6}\\.(?:SH|SZ|BJ)$" },
    conviction: { type: "number", exclusiveMinimum: 0, maximum: 1 },
    thesis: conciseProviderText(),
  };
  return {
    type: "object",
    properties,
    required: Object.keys(properties),
    additionalProperties: false,
  };
}

function materializeSelectedSector(input: Record<string, unknown>): unknown {
  const agent = String(input.agent);
  const preferredDirectionId = String(input.preferred_direction_id);
  const preferredDirectionLocalId = String(input.preferred_direction_local_id);
  const leastDirectionId = optionalString(input.least_preferred_direction_id);
  const leastDirectionLocalId = optionalString(input.least_preferred_direction_local_id);
  const claimId = `provider-${agent}-selection-claim`.slice(0, 128);
  const claimRefs = [claimId];
  const preferredSecurity = materializeSecurityLeg({
    value: input.preferred_security,
    agent,
    directionLocalId: preferredDirectionLocalId,
    action: "LONG",
    claimRefs,
  });
  const leastSecurity = materializeSecurityLeg({
    value: input.least_preferred_security,
    agent,
    directionLocalId: leastDirectionLocalId,
    action: "AVOID",
    claimRefs,
  });
  const preferredThesis = String(input.preferred_thesis);
  return {
    agent,
    selection_status: "SELECTED",
    preferred_direction: {
      selection_role: "PREFERRED",
      direction_local_id: preferredDirectionLocalId,
      direction_id: preferredDirectionId,
      allocation_action: "OVERWEIGHT",
      strength: input.preferred_strength,
      thesis: preferredThesis,
      claim_refs: claimRefs,
    },
    least_preferred_direction:
      leastDirectionId && leastDirectionLocalId
        ? {
            selection_role: "LEAST_PREFERRED",
            direction_local_id: leastDirectionLocalId,
            direction_id: leastDirectionId,
            allocation_action: "UNDERWEIGHT",
            strength: input.least_preferred_strength,
            thesis: input.least_preferred_thesis,
            claim_refs: claimRefs,
          }
        : {
            status: "NO_QUALIFIED_AVOID_DIRECTION",
            reason: input.least_preferred_reason,
          },
    persistence_horizon: input.persistence_horizon,
    confidence: input.confidence,
    key_drivers: [
      {
        driver_local_id: `provider-${agent}-selection-driver`.slice(0, 128),
        summary: input.driver_summary,
        claim_refs: claimRefs,
      },
    ],
    risks: [
      {
        risk_local_id: `provider-${agent}-selection-risk`.slice(0, 128),
        summary: input.risk_summary,
        claim_refs: claimRefs,
      },
    ],
    claims: [
      {
        claim_id: claimId,
        claim_kind: "INTERPRETATION",
        statement: preferredThesis,
        structured_conclusion: {
          conclusion_type: "SECTOR_DIRECTION",
          target_local_ref: preferredDirectionLocalId,
          selection_status: "SELECTED",
          direction_id: preferredDirectionId,
          position_action: null,
          summary: preferredThesis,
        },
        evidence_ids: [input.evidence_id],
        research_rule_refs: [input.research_rule_ref],
      },
    ],
    claim_refs: claimRefs,
    macro_input_attributions: input.macro_input_attributions,
    preferred_security_status: preferredSecurity.status,
    preferred_security_abstention_confidence: preferredSecurity.abstentionConfidence,
    long_picks: preferredSecurity.picks,
    least_preferred_security_status: leastSecurity.status,
    least_preferred_security_abstention_confidence: leastSecurity.abstentionConfidence,
    short_or_avoid_picks: leastSecurity.picks,
  };
}

function materializeSecurityLeg(input: {
  value: unknown;
  agent: string;
  directionLocalId: string | null;
  action: "LONG" | "AVOID";
  claimRefs: string[];
}): {
  status: "PICKS_PRESENT" | "NO_QUALIFIED_SECURITY" | "NOT_APPLICABLE";
  abstentionConfidence: number | null;
  picks: Array<Record<string, unknown>>;
} {
  const record = objectRecord(input.value) ?? {};
  if (record.status === "NOT_APPLICABLE") {
    return { status: "NOT_APPLICABLE", abstentionConfidence: null, picks: [] };
  }
  if (record.status !== "PICKS_PRESENT" || !input.directionLocalId) {
    return {
      status: "NO_QUALIFIED_SECURITY",
      abstentionConfidence:
        typeof record.abstention_confidence === "number" ? record.abstention_confidence : 0,
      picks: [],
    };
  }
  const rows = Array.isArray(record.picks) ? record.picks : [];
  const picks = rows.flatMap((value, index) => {
    const row = objectRecord(value);
    if (!row || typeof row.ts_code !== "string") return [];
    return [
      {
        pick_local_id: `provider-${input.agent}-${input.action.toLowerCase()}-${index + 1}`.slice(
          0,
          128,
        ),
        ts_code: row.ts_code,
        direction_local_id: input.directionLocalId,
        position_action: input.action,
        conviction: row.conviction,
        thesis: row.thesis,
        claim_refs: input.claimRefs,
      },
    ];
  });
  return { status: "PICKS_PRESENT", abstentionConfidence: null, picks };
}

function conciseProviderText(): Record<string, unknown> {
  return { type: "string", minLength: 1, maxLength: 160 };
}

function runtimeEvidenceIdProviderSchema(): Record<string, unknown> {
  return { type: "string", pattern: "^evidence:[0-9a-f]{64}$", maxLength: 73 };
}

function arrayCapacity(value: unknown): number {
  const schema = objectRecord(value);
  if (!schema) return 0;
  if (typeof schema.maxItems === "number") return Math.max(0, schema.maxItems);
  if (Array.isArray(schema.prefixItems)) return schema.prefixItems.length;
  return 5;
}

function boundedArrayCapacity(value: unknown): number | null {
  const schema = objectRecord(value);
  if (!schema) return null;
  if (typeof schema.maxItems === "number") return Math.max(0, schema.maxItems);
  if (Array.isArray(schema.prefixItems)) return schema.prefixItems.length;
  return null;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function isSectorAbstentionProviderPayload(value: Record<string, unknown>): boolean {
  return (
    typeof value.agent === "string" &&
    STANDARD_SECTOR_AGENTS.has(value.agent) &&
    typeof value.least_preferred_reason === "string" &&
    typeof value.persistence_horizon === "string" &&
    typeof value.confidence === "number" &&
    typeof value.abstention_summary === "string" &&
    typeof value.evidence_id === "string" &&
    value.macro_input_attributions !== undefined
  );
}

function objectRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function schemaConst(value: unknown): string | null {
  const record = objectRecord(value);
  return typeof record?.const === "string" ? record.const : null;
}
