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
const COMPACT_MACRO_COMPONENTS = "MACRO_COMPONENTS_COMPACT_V1";
const COMPACT_MACRO_DIRECT = "MACRO_DIRECT_COMPACT_V1";
const SUPERINVESTOR_AGENTS = new Set(["druckenmiller", "munger", "burry", "ackman"]);

export const STRUCTURED_PROVIDER_ADAPTER_DESCRIPTOR = Object.freeze({
  contract_version: "structured_provider_adapter_pipeline_v3",
  adapter_pipeline: [
    "SECTOR_DIRECTION_PROVIDER_ADAPTER_V2",
    "SECTOR_FINAL_PROVIDER_ADAPTER_V2",
    "MACRO_PROVIDER_ADAPTER_V2",
    "MACRO_ATTRIBUTION_PROVIDER_ADAPTER_V1",
    "STRICT_PROVIDER_PAYLOAD_NORMALIZATION_V2",
  ],
  compact_contracts: [
    "SECTOR_DIRECTION_RESEARCH_COMPACT_V2",
    "SECTOR_CONFLICT_REVIEW_COMPACT_V2",
    COMPACT_SELECTED_SECTOR,
    COMPACT_RELATIONSHIP_MAPPER,
    COMPACT_SUPERINVESTOR_ABSTENTION,
    COMPACT_MACRO_COMPONENTS,
    COMPACT_MACRO_DIRECT,
  ],
  macro_materialization:
    "ONE_MODEL_JUDGMENT_TO_ONE_RUNTIME_OWNED_CLAIM_WITH_EXACT_COMPONENT_SUBJECT_V1",
  macro_narrative_projection:
    "BOUNDED_COMPLETE_QUALITATIVE_PROSE_WITH_CANONICAL_NUMBER_WORD_AND_PLACEHOLDER_GUARD_V1",
  sector_security_materialization:
    "DISTINCT_DIRECTION_DRIVER_RISK_AND_PER_SECURITY_CAUSAL_CLAIMS_V2",
});

export const MACRO_PROVIDER_INSTRUCTION =
  "The bounded Macro extraction contract is MACRO_COMPONENTS_COMPACT_V1 or " +
  "MACRO_DIRECT_COMPACT_V1. Return only the fields requested by that compact schema. For every " +
  "component or direct signal, copy one exact evidence_id. Copy an exact permitted citation id " +
  "into research_rule_ref when the catalog supplies one; otherwise set it to null and do not " +
  "select INTERPRETATION. Set snapshot_echo to null: the compact extraction path deliberately " +
  "omits optional numeric echoes while the canonical contract retains them for other clients. Runtime " +
  "deterministically creates canonical claim ids, key_drivers, and claim_refs without changing " +
  "your direction, strength, horizon, confidence, channel, claim kind, conclusion, evidence, or " +
  "snapshot-echo judgments. Narrative fields must omit numeric facts completely; never evade this " +
  "by spelling numbers in Chinese or English. Do not return direction words or empty-value tokens " +
  "as narrative placeholders, and finish every sentence without a dangling fragment. In " +
  "COMPONENTS mode every component becomes one independently owned " +
  "claim whose canonical structured_conclusion.subject is exactly that component id.";

export const SECTOR_SELECTED_PROVIDER_INSTRUCTION =
  "When the bounded provider extraction contract is SECTOR_SELECTED_COMPACT_V1, return the exact " +
  "runtime-owned direction ids, concise preferred/least theses, one driver, one risk, one accepted " +
  "evidence_id, security-leg decisions with LONG on the preferred leg and SHORT or AVOID on the " +
  "least-preferred leg, and Macro attributions. Runtime deterministically assigns local ids and " +
  "maps each explicit direction, driver, risk, and security judgment to its own claim/reference " +
  "envelope without changing your direction, strength, confidence, security, or Macro-attribution " +
  "judgments.";

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
    adaptMacroProviderJsonSchema(
      adaptSectorFinalJsonSchema(adaptSectorDirectionProviderJsonSchema(value)),
    ),
  );
}

export function normalizeStrictProviderPayload(value: unknown): unknown {
  return normalizeMacroAttributionProviderPayload(
    normalizeMacroProviderPayload(
      normalizeSectorFinalPayload(normalizeSectorDirectionProviderPayload(value)),
    ),
  );
}

function adaptMacroProviderJsonSchema(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(adaptMacroProviderJsonSchema);
  if (value === null || typeof value !== "object") return value;
  const record = value as Record<string, unknown>;
  const properties = objectRecord(record.properties);
  const compact = macroProviderSchema(properties);
  if (compact) return compact;
  return Object.fromEntries(
    Object.entries(record).map(([key, nested]) => [key, adaptMacroProviderJsonSchema(nested)]),
  );
}

function macroProviderSchema(
  properties: Record<string, unknown> | null,
): Record<string, unknown> | null {
  if (!properties?.claims || !properties.key_drivers) return null;
  const mode = schemaConst(properties.mode);
  if (mode !== "COMPONENTS" && mode !== "DIRECT") return null;
  const claimProperties = objectRecord(objectRecord(properties.claims)?.items)?.properties;
  const claims = objectRecord(claimProperties);
  const conclusion = objectRecord(objectRecord(claims?.structured_conclusion)?.properties);
  if (!claims || !conclusion) return null;
  if (mode === "COMPONENTS") {
    const components = macroComponentSourceProperties(properties.components);
    if (components.length === 0) return null;
    const compactComponents = components.map(({ component, properties: source }) =>
      compactMacroJudgmentSchema({ component, source, claims, conclusion }),
    );
    if (compactComponents.some((component) => component === null)) return null;
    const compactProperties = {
      provider_contract: { type: "string", const: COMPACT_MACRO_COMPONENTS },
      mode: properties.mode,
      components: {
        type: "array",
        prefixItems: compactComponents,
        items: false,
        minItems: components.length,
        maxItems: components.length,
      },
    };
    return {
      type: "object",
      properties: compactProperties,
      required: Object.keys(compactProperties),
      additionalProperties: false,
    };
  }
  const signalSource = macroDirectSignalSourceProperties(properties.signal);
  if (!signalSource) return null;
  const judgment = compactMacroJudgmentSchema({
    source: signalSource,
    claims,
    conclusion,
    includeSubject: true,
  });
  if (!judgment) return null;
  const compactProperties = {
    provider_contract: { type: "string", const: COMPACT_MACRO_DIRECT },
    mode: properties.mode,
    judgment,
  };
  return {
    type: "object",
    properties: compactProperties,
    required: Object.keys(compactProperties),
    additionalProperties: false,
  };
}

function compactMacroJudgmentSchema(input: {
  source: Record<string, unknown>;
  claims: Record<string, unknown>;
  conclusion: Record<string, unknown>;
  component?: string;
  includeSubject?: boolean;
}): Record<string, unknown> | null {
  const channel = objectRecord(input.source.channels)?.items;
  if (
    !input.source.persistence_horizon ||
    !input.source.confidence ||
    !channel ||
    !input.claims.claim_kind ||
    !input.claims.statement ||
    !input.conclusion.state ||
    !input.conclusion.a_share_transmission
  ) {
    return null;
  }
  const properties: Record<string, unknown> = {
    ...(input.component ? { component: { type: "string", const: input.component } } : {}),
    signal: compactMacroDirectionStrengthSchema(),
    persistence_horizon: input.source.persistence_horizon,
    confidence: input.source.confidence,
    channel: boundedMacroNarrativeSchema(channel, 96),
    claim_kind: input.claims.claim_kind,
    statement: boundedMacroNarrativeSchema(input.claims.statement, 160),
    ...(input.includeSubject
      ? { subject: boundedMacroNarrativeSchema(input.conclusion.subject, 96) }
      : {}),
    state: boundedMacroNarrativeSchema(input.conclusion.state, 128),
    a_share_transmission: boundedMacroNarrativeSchema(input.conclusion.a_share_transmission, 160),
    evidence_id: runtimeEvidenceIdProviderSchema(),
    research_rule_ref: {
      anyOf: [
        { type: "null" },
        {
          type: "string",
          minLength: 1,
          maxLength: 64,
          pattern: "^[A-Za-z][A-Za-z0-9_.:-]{0,63}$",
        },
      ],
    },
    snapshot_echo: { type: "null" },
  };
  return {
    type: "object",
    properties,
    required: Object.keys(properties),
    additionalProperties: false,
  };
}

function compactMacroDirectionStrengthSchema(): Record<string, unknown> {
  const neutralProperties = {
    direction: { type: "string", const: "NEUTRAL" },
    strength: { type: "number", const: 0 },
  };
  const activeProperties = {
    direction: { type: "string", enum: ["SUPPORTIVE", "ADVERSE"] },
    strength: { type: "number", enum: [1, 2, 3, 4, 5] },
  };
  return {
    anyOf: [
      {
        type: "object",
        properties: neutralProperties,
        required: Object.keys(neutralProperties),
        additionalProperties: false,
      },
      {
        type: "object",
        properties: activeProperties,
        required: Object.keys(activeProperties),
        additionalProperties: false,
      },
    ],
  };
}

function macroComponentSourceProperties(
  value: unknown,
): Array<{ component: string; properties: Record<string, unknown> }> {
  const byComponent = new Map<string, Record<string, unknown>>();
  visitSchema(value, (record) => {
    const properties = objectRecord(record.properties);
    const component = schemaConst(properties?.component);
    if (
      component &&
      properties?.direction &&
      properties.strength &&
      properties.persistence_horizon &&
      !byComponent.has(component)
    ) {
      byComponent.set(component, properties);
    }
  });
  return [...byComponent.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([component, properties]) => ({ component, properties }));
}

function macroDirectSignalSourceProperties(value: unknown): Record<string, unknown> | null {
  let found: Record<string, unknown> | null = null;
  visitSchema(value, (record) => {
    const properties = objectRecord(record.properties);
    if (
      !found &&
      properties?.direction &&
      properties.strength &&
      properties.persistence_horizon &&
      properties.confidence &&
      properties.channels
    ) {
      found = properties;
    }
  });
  return found;
}

function visitSchema(value: unknown, visitor: (record: Record<string, unknown>) => void): void {
  if (Array.isArray(value)) {
    for (const nested of value) visitSchema(nested, visitor);
    return;
  }
  const record = objectRecord(value);
  if (!record) return;
  visitor(record);
  for (const nested of Object.values(record)) visitSchema(nested, visitor);
}

function boundedMacroNarrativeSchema(value: unknown, maxLength: number): Record<string, unknown> {
  return {
    ...boundedIdentifierSchema(value, maxLength, `^[^0-9０-９%％\\r\\n]{1,${maxLength}}$`),
    description:
      "Complete qualitative prose only. Omit numeric facts entirely: do not spell numbers in " +
      "Chinese or English, do not use tenor phrases such as written-out year counts, and do not " +
      "return direction/empty-value placeholders or truncated fragments.",
  };
}

function boundedIdentifierSchema(
  value: unknown,
  maxLength: number,
  pattern: string,
): Record<string, unknown> {
  const source = objectRecord(value) ?? { type: "string" };
  return {
    ...source,
    minLength: typeof source.minLength === "number" ? Math.max(1, source.minLength) : 1,
    maxLength:
      typeof source.maxLength === "number" ? Math.min(source.maxLength, maxLength) : maxLength,
    pattern,
  };
}

function normalizeMacroProviderPayload(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalizeMacroProviderPayload);
  if (value === null || typeof value !== "object") return value;
  const record = value as Record<string, unknown>;
  if (record.provider_contract === COMPACT_MACRO_COMPONENTS) {
    return materializeMacroComponents(record);
  }
  if (record.provider_contract === COMPACT_MACRO_DIRECT) {
    return materializeMacroDirect(record);
  }
  return Object.fromEntries(
    Object.entries(record).map(([key, nested]) => [key, normalizeMacroProviderPayload(nested)]),
  );
}

function materializeMacroComponents(input: Record<string, unknown>): unknown {
  const rows = Array.isArray(input.components) ? input.components : [];
  const materialized = rows.flatMap((value) => {
    const row = objectRecord(value);
    if (!row) return [];
    const component = requiredString(row.component, "component");
    return [materializeMacroJudgment(row, component, `provider-macro-${component}-claim`)];
  });
  return {
    mode: "COMPONENTS",
    claims: materialized.map((entry) => entry.claim),
    key_drivers: materialized.map((entry) => entry.claim.statement),
    components: materialized.map((entry) => ({ component: entry.subject, ...entry.signal })),
  };
}

function materializeMacroDirect(input: Record<string, unknown>): unknown {
  const row = objectRecord(input.judgment) ?? {};
  const subject = requiredString(row.subject, "subject");
  const materialized = materializeMacroJudgment(row, subject, "provider-macro-direct-claim");
  return {
    mode: "DIRECT",
    claims: [materialized.claim],
    key_drivers: [materialized.claim.statement],
    signal: materialized.signal,
  };
}

function materializeMacroJudgment(
  input: Record<string, unknown>,
  subject: string,
  claimId: string,
): {
  subject: string;
  claim: Record<string, unknown>;
  signal: Record<string, unknown>;
} {
  const directionStrength = objectRecord(input.signal) ?? {};
  const snapshotEcho = objectRecord(input.snapshot_echo);
  const kind = String(input.claim_kind);
  const claim = {
    claim_id: claimId.slice(0, 128),
    claim_kind: input.claim_kind,
    statement: input.statement,
    structured_conclusion: {
      conclusion_type: macroConclusionType(kind),
      subject,
      state: input.state,
      a_share_transmission: input.a_share_transmission,
      snapshot_echo_id: snapshotEcho?.snapshot_echo_id ?? null,
      snapshot_metric: snapshotEcho?.snapshot_metric ?? null,
      snapshot_value: snapshotEcho?.snapshot_value ?? null,
    },
    evidence_ids: [input.evidence_id],
    research_rule_refs:
      typeof input.research_rule_ref === "string" ? [input.research_rule_ref] : [],
  };
  return {
    subject,
    claim,
    signal: {
      direction: directionStrength.direction,
      strength: directionStrength.strength,
      persistence_horizon: input.persistence_horizon,
      evaluation_horizon_trading_days: 5,
      confidence: input.confidence,
      channels: [input.channel],
      claim_refs: [claim.claim_id],
    },
  };
}

function macroConclusionType(kind: string): string {
  const byKind: Readonly<Record<string, string>> = {
    FACT: "MACRO_FACT",
    EVENT: "MACRO_EVENT",
    INTERPRETATION: "MACRO_INTERPRETATION",
    RISK_FLAG: "MACRO_RISK",
  };
  return byKind[kind] ?? "MACRO_RISK";
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
      uniqueItems: true,
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
      uniqueItems: true,
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
  if (
    !preferredDirectionId ||
    !preferredDirectionLocalId ||
    !leastDirectionId ||
    !leastDirectionLocalId ||
    !preferredProperties?.strength ||
    !properties.persistence_horizon ||
    !properties.confidence ||
    !properties.macro_input_attributions
  ) {
    return null;
  }
  const preferredCapacity = arrayCapacity(properties.long_picks);
  const leastCapacity = arrayCapacity(properties.short_or_avoid_picks);
  const preferredSecurityStatus = schemaConst(properties.preferred_security_status);
  const leastSecurityStatus = schemaConst(properties.least_preferred_security_status);
  const compactProperties: Record<string, unknown> = {
    provider_contract: { type: "string", const: COMPACT_SELECTED_SECTOR },
    agent: properties.agent,
    preferred_direction_id: preferredProperties.direction_id,
    preferred_direction_local_id: preferredProperties.direction_local_id,
    preferred_strength: preferredProperties.strength,
    preferred_thesis: conciseProviderText(),
    least_preferred_direction_id: leastProperties?.direction_id,
    least_preferred_direction_local_id: leastProperties?.direction_local_id,
    least_preferred_strength: leastProperties?.strength,
    least_preferred_thesis: conciseProviderText(),
    persistence_horizon: properties.persistence_horizon,
    confidence: properties.confidence,
    driver_summary: conciseProviderText(),
    risk_summary: conciseProviderText(),
    evidence_id: runtimeEvidenceIdProviderSchema(),
    research_rule_ref: { type: "string", minLength: 1, maxLength: 256 },
    preferred_security: compactSecurityLegSchema(preferredCapacity, preferredSecurityStatus, {
      type: "string",
      const: "LONG",
    }),
    least_preferred_security: compactSecurityLegSchema(leastCapacity, leastSecurityStatus, {
      type: "string",
      enum: ["SHORT", "AVOID"],
    }),
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
  requiredStatus: string | null,
  positionAction: Record<string, unknown>,
): Record<string, unknown> {
  const noQualified = {
    type: "object",
    properties: {
      status: { type: "string", const: "NO_QUALIFIED_SECURITY" },
      abstention_confidence: { type: "number", minimum: 0, maximum: 1 },
    },
    required: ["status", "abstention_confidence"],
    additionalProperties: false,
  };
  if (capacity === 0 || requiredStatus === "NO_QUALIFIED_SECURITY") return noQualified;
  const picksPresent = {
    type: "object",
    properties: {
      status: { type: "string", const: "PICKS_PRESENT" },
      picks: {
        type: "array",
        items: compactSecurityPickSchema(positionAction),
        minItems: 1,
        maxItems: capacity,
      },
    },
    required: ["status", "picks"],
    additionalProperties: false,
  };
  return requiredStatus === "PICKS_PRESENT" ? picksPresent : { anyOf: [picksPresent, noQualified] };
}

function compactSecurityPickSchema(
  positionAction: Record<string, unknown>,
): Record<string, unknown> {
  const properties = {
    ts_code: { type: "string", pattern: "^\\d{6}\\.(?:SH|SZ|BJ)$" },
    position_action: positionAction,
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
  const leastDirectionId = requiredString(
    input.least_preferred_direction_id,
    "least_preferred_direction_id",
  );
  const leastDirectionLocalId = requiredString(
    input.least_preferred_direction_local_id,
    "least_preferred_direction_local_id",
  );
  const preferredClaimId = `provider-${agent}-preferred-direction-claim`.slice(0, 128);
  const leastClaimId = `provider-${agent}-least-direction-claim`.slice(0, 128);
  const driverClaimId = `provider-${agent}-driver-claim`.slice(0, 128);
  const riskClaimId = `provider-${agent}-risk-claim`.slice(0, 128);
  const preferredSecurity = materializeSecurityLeg({
    value: input.preferred_security,
    agent,
    directionLocalId: preferredDirectionLocalId,
    leg: "preferred",
  });
  const leastSecurity = materializeSecurityLeg({
    value: input.least_preferred_security,
    agent,
    directionLocalId: leastDirectionLocalId,
    leg: "least",
  });
  const preferredThesis = String(input.preferred_thesis);
  const leastThesis = String(input.least_preferred_thesis);
  const driverSummary = String(input.driver_summary);
  const riskSummary = String(input.risk_summary);
  const evidenceIds = [input.evidence_id];
  const researchRuleRefs = [input.research_rule_ref];
  const securityClaims = [...preferredSecurity.picks, ...leastSecurity.picks].map((pick) => ({
    claim_id: String((pick.claim_refs as string[])[0]),
    claim_kind: "INTERPRETATION",
    statement: pick.thesis,
    structured_conclusion: {
      conclusion_type: "SECTOR_SECURITY",
      target_local_ref: pick.pick_local_id,
      selection_status: "SELECTED",
      direction_id:
        pick.direction_local_id === preferredDirectionLocalId
          ? preferredDirectionId
          : leastDirectionId,
      position_action: pick.position_action,
      summary: pick.thesis,
    },
    evidence_ids: evidenceIds,
    research_rule_refs: researchRuleRefs,
  }));
  const claims = [
    {
      claim_id: preferredClaimId,
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
      evidence_ids: evidenceIds,
      research_rule_refs: researchRuleRefs,
    },
    {
      claim_id: leastClaimId,
      claim_kind: "INTERPRETATION",
      statement: leastThesis,
      structured_conclusion: {
        conclusion_type: "SECTOR_DIRECTION",
        target_local_ref: leastDirectionLocalId,
        selection_status: "SELECTED",
        direction_id: leastDirectionId,
        position_action: null,
        summary: leastThesis,
      },
      evidence_ids: evidenceIds,
      research_rule_refs: researchRuleRefs,
    },
    {
      claim_id: driverClaimId,
      claim_kind: "INTERPRETATION",
      statement: driverSummary,
      structured_conclusion: {
        conclusion_type: "SECTOR_DRIVER",
        target_local_ref: `provider-${agent}-selection-driver`.slice(0, 128),
        selection_status: "SELECTED",
        direction_id: null,
        position_action: null,
        summary: driverSummary,
      },
      evidence_ids: evidenceIds,
      research_rule_refs: researchRuleRefs,
    },
    {
      claim_id: riskClaimId,
      claim_kind: "RISK_FLAG",
      statement: riskSummary,
      structured_conclusion: {
        conclusion_type: "SECTOR_RISK",
        target_local_ref: `provider-${agent}-selection-risk`.slice(0, 128),
        selection_status: "SELECTED",
        direction_id: null,
        position_action: null,
        summary: riskSummary,
      },
      evidence_ids: evidenceIds,
      research_rule_refs: researchRuleRefs,
    },
    ...securityClaims,
  ];
  const claimRefs = claims.map((claim) => claim.claim_id);
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
      claim_refs: [preferredClaimId],
    },
    least_preferred_direction: {
      selection_role: "LEAST_PREFERRED",
      direction_local_id: leastDirectionLocalId,
      direction_id: leastDirectionId,
      allocation_action: "UNDERWEIGHT",
      strength: input.least_preferred_strength,
      thesis: leastThesis,
      claim_refs: [leastClaimId],
    },
    persistence_horizon: input.persistence_horizon,
    confidence: input.confidence,
    key_drivers: [
      {
        driver_local_id: `provider-${agent}-selection-driver`.slice(0, 128),
        summary: driverSummary,
        claim_refs: [driverClaimId],
      },
    ],
    risks: [
      {
        risk_local_id: `provider-${agent}-selection-risk`.slice(0, 128),
        summary: riskSummary,
        claim_refs: [riskClaimId],
      },
    ],
    claims,
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
  directionLocalId: string;
  leg: "preferred" | "least";
}): {
  status: "PICKS_PRESENT" | "NO_QUALIFIED_SECURITY";
  abstentionConfidence: number | null;
  picks: Array<Record<string, unknown>>;
} {
  const record = objectRecord(input.value) ?? {};
  if (record.status !== "PICKS_PRESENT") {
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
    const pickLocalId = `provider-${input.agent}-${input.leg}-security-${index + 1}`.slice(0, 128);
    const claimId = `${pickLocalId}-claim`.slice(0, 128);
    return [
      {
        pick_local_id: pickLocalId,
        ts_code: row.ts_code,
        direction_local_id: input.directionLocalId,
        position_action: row.position_action,
        conviction: row.conviction,
        thesis: row.thesis,
        claim_refs: [claimId],
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

function requiredString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${field} must be a non-empty string`);
  }
  return value;
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
