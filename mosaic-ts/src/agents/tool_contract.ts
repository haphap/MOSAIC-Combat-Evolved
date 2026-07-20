import { z } from "zod";

export const AGENT_TOOL_CONTRACT_VERSION = "agent_tool_contract_manifest_v1";
export const SNAPSHOT_BUNDLE_CONTRACT_VERSION = "agent_snapshot_bundle_v1";
export const CAPABILITY_CONTRACT_VERSION = "agent_tool_capability_v1";

export const AGENT_TOOL_IDS = [
  "get_china_macro_snapshot",
  "get_us_macro_snapshot",
  "get_eu_macro_snapshot",
  "get_central_bank_snapshot",
  "get_us_financial_conditions_snapshot",
  "get_euro_area_financial_conditions_snapshot",
  "get_commodity_conditions_snapshot",
  "get_geopolitical_events_snapshot",
  "get_market_breadth_snapshot",
  "get_market_positioning_snapshot",
  "get_sector_research_snapshot",
  "get_role_event_snapshot",
  "get_relationship_graph_snapshot",
  "get_superinvestor_candidate_snapshot",
  "get_cro_risk_snapshot",
  "get_alpha_candidate_snapshot",
  "get_execution_snapshot",
  "get_cio_decision_snapshot",
] as const;

export const AGENT_IDS = [
  "china",
  "us_economy",
  "eu_economy",
  "central_bank",
  "us_financial_conditions",
  "euro_area_financial_conditions",
  "commodities",
  "geopolitical",
  "market_breadth",
  "institutional_flow",
  "semiconductor",
  "technology",
  "energy",
  "biotech",
  "consumer",
  "industrials",
  "real_estate_construction",
  "financials",
  "agriculture",
  "relationship_mapper",
  "druckenmiller",
  "munger",
  "burry",
  "ackman",
  "cro",
  "alpha_discovery",
  "autonomous_execution",
  "cio",
] as const;

export const AGENT_EXECUTION_STAGE_IDS = [
  "china",
  "us_economy",
  "eu_economy",
  "central_bank",
  "us_financial_conditions",
  "euro_area_financial_conditions",
  "commodities",
  "geopolitical",
  "market_breadth",
  "institutional_flow",
  "semiconductor",
  "technology",
  "energy",
  "biotech",
  "consumer",
  "industrials",
  "real_estate_construction",
  "financials",
  "agriculture",
  "relationship_mapper",
  "druckenmiller",
  "munger",
  "burry",
  "ackman",
  "cro",
  "alpha_discovery",
  "autonomous_execution",
  "cio_proposal",
  "cio_final",
] as const;

export type AgentToolId = (typeof AGENT_TOOL_IDS)[number];
export type AgentId = (typeof AGENT_IDS)[number];
export type AgentExecutionStageId = (typeof AGENT_EXECUTION_STAGE_IDS)[number];
export type AgentLayer = "macro" | "sector" | "superinvestor" | "decision";

export const AgentToolIdSchema = z.enum(AGENT_TOOL_IDS);
export const AgentIdSchema = z.enum(AGENT_IDS);
export const AgentExecutionStageIdSchema = z.enum(AGENT_EXECUTION_STAGE_IDS);

export const AGENT_LAYER_BY_ID = {
  china: "macro",
  us_economy: "macro",
  eu_economy: "macro",
  central_bank: "macro",
  us_financial_conditions: "macro",
  euro_area_financial_conditions: "macro",
  commodities: "macro",
  geopolitical: "macro",
  market_breadth: "macro",
  institutional_flow: "macro",
  semiconductor: "sector",
  technology: "sector",
  energy: "sector",
  biotech: "sector",
  consumer: "sector",
  industrials: "sector",
  real_estate_construction: "sector",
  financials: "sector",
  agriculture: "sector",
  relationship_mapper: "sector",
  druckenmiller: "superinvestor",
  munger: "superinvestor",
  burry: "superinvestor",
  ackman: "superinvestor",
  cro: "decision",
  alpha_discovery: "decision",
  autonomous_execution: "decision",
  cio: "decision",
} as const satisfies Readonly<Record<AgentId, AgentLayer>>;

export const AGENT_TOOL_MATRIX = {
  china: ["get_china_macro_snapshot"],
  us_economy: ["get_us_macro_snapshot"],
  eu_economy: ["get_eu_macro_snapshot"],
  central_bank: ["get_central_bank_snapshot"],
  us_financial_conditions: ["get_us_financial_conditions_snapshot"],
  euro_area_financial_conditions: ["get_euro_area_financial_conditions_snapshot"],
  commodities: ["get_commodity_conditions_snapshot"],
  geopolitical: ["get_geopolitical_events_snapshot"],
  market_breadth: ["get_market_breadth_snapshot"],
  institutional_flow: ["get_market_positioning_snapshot"],
  semiconductor: ["get_sector_research_snapshot", "get_role_event_snapshot"],
  technology: ["get_sector_research_snapshot", "get_role_event_snapshot"],
  energy: ["get_sector_research_snapshot", "get_role_event_snapshot"],
  biotech: ["get_sector_research_snapshot"],
  consumer: ["get_sector_research_snapshot", "get_role_event_snapshot"],
  industrials: ["get_sector_research_snapshot", "get_role_event_snapshot"],
  real_estate_construction: ["get_sector_research_snapshot", "get_role_event_snapshot"],
  financials: ["get_sector_research_snapshot", "get_role_event_snapshot"],
  agriculture: ["get_sector_research_snapshot", "get_role_event_snapshot"],
  relationship_mapper: ["get_relationship_graph_snapshot"],
  druckenmiller: ["get_superinvestor_candidate_snapshot"],
  munger: ["get_superinvestor_candidate_snapshot"],
  burry: ["get_superinvestor_candidate_snapshot"],
  ackman: ["get_superinvestor_candidate_snapshot"],
  cro: ["get_cro_risk_snapshot", "get_role_event_snapshot"],
  alpha_discovery: ["get_alpha_candidate_snapshot", "get_role_event_snapshot"],
  autonomous_execution: ["get_execution_snapshot", "get_role_event_snapshot"],
  cio: ["get_cio_decision_snapshot"],
} as const satisfies Readonly<Record<AgentId, readonly [AgentToolId, ...AgentToolId[]]>>;

export function agentToolsFor(agentId: AgentId): readonly [AgentToolId, ...AgentToolId[]] {
  return AGENT_TOOL_MATRIX[agentId];
}

export function executionStagesFor(
  agentId: AgentId,
): readonly [AgentExecutionStageId, ...AgentExecutionStageId[]] {
  return agentId === "cio" ? ["cio_proposal", "cio_final"] : [agentId];
}

const Id = z.string().trim().min(1);
const Sha256 = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const IsoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const IsoDateTime = z.iso.datetime({ offset: true });

export const AgentSnapshotBundleSchema = z
  .object({
    snapshot_bundle_id: Id,
    snapshot_bundle_hash: Sha256,
    snapshot_bundle_contract_version: z.literal(SNAPSHOT_BUNDLE_CONTRACT_VERSION),
    materialization_request_id: Id,
    agent_id: AgentIdSchema,
    stage: AgentExecutionStageIdSchema,
    as_of: IsoDate,
    candidate_scope_hash: Sha256.nullable(),
    runtime_input_hash: Sha256,
    tool_payload_hashes: z.partialRecord(AgentToolIdSchema, Sha256),
    materialized_at: IsoDateTime,
  })
  .strict()
  .superRefine((bundle, ctx) => {
    if (!executionStagesFor(bundle.agent_id).includes(bundle.stage)) {
      ctx.addIssue({ code: "custom", path: ["stage"], message: "agent/stage mismatch" });
    }
    const tools = Object.keys(bundle.tool_payload_hashes).sort();
    const expected = [...agentToolsFor(bundle.agent_id)].sort();
    if (tools.join("\0") !== expected.join("\0")) {
      ctx.addIssue({
        code: "custom",
        path: ["tool_payload_hashes"],
        message: "tool payload keys must exactly match the role whitelist",
      });
    }
  });

export const AgentToolCapabilityManifestSchema = z
  .object({
    capability_contract_version: z.literal(CAPABILITY_CONTRACT_VERSION),
    capability_id: Id,
    graph_run_id: Id,
    run_slot_id: Id,
    run_id: Id,
    node_id: Id,
    agent_id: AgentIdSchema,
    stage: AgentExecutionStageIdSchema,
    allowed_tools: z.array(AgentToolIdSchema).min(1),
    as_of: IsoDate,
    candidate_scope_hash: Sha256.nullable(),
    snapshot_bundle_id: Id,
    snapshot_bundle_hash: Sha256,
    issued_at: IsoDateTime,
    expires_at: IsoDateTime,
    nonce: Id,
  })
  .strict()
  .superRefine((manifest, ctx) => {
    if (!executionStagesFor(manifest.agent_id).includes(manifest.stage)) {
      ctx.addIssue({ code: "custom", path: ["stage"], message: "agent/stage mismatch" });
    }
    const tools = [...manifest.allowed_tools].sort();
    const expected = [...agentToolsFor(manifest.agent_id)].sort();
    if (new Set(tools).size !== tools.length || tools.join("\0") !== expected.join("\0")) {
      ctx.addIssue({
        code: "custom",
        path: ["allowed_tools"],
        message: "allowed tools must exactly match the role whitelist",
      });
    }
  });

export const SignedAgentToolCapabilitySchema = z
  .object({
    manifest: AgentToolCapabilityManifestSchema,
    signing_key_id: Id,
    signature: z.string().regex(/^hmac-sha256:[0-9a-f]{64}$/),
  })
  .strict();

export type AgentSnapshotBundle = z.infer<typeof AgentSnapshotBundleSchema>;
export type AgentToolCapabilityManifest = z.infer<typeof AgentToolCapabilityManifestSchema>;
export type SignedAgentToolCapability = z.infer<typeof SignedAgentToolCapabilitySchema>;

export const AgentToolContractManifestSchema = z
  .object({
    schema_version: z.literal(AGENT_TOOL_CONTRACT_VERSION),
    agent_count: z.literal(28),
    execution_stage_count: z.literal(29),
    tool_count: z.literal(18),
    agents: z
      .array(
        z
          .object({
            agent_id: AgentIdSchema,
            layer: z.enum(["macro", "sector", "superinvestor", "decision"]),
            execution_stages: z.array(AgentExecutionStageIdSchema).min(1),
            allowed_tools: z.array(AgentToolIdSchema).min(1),
          })
          .strict(),
      )
      .length(28),
  })
  .strict();

export type AgentToolContractManifest = z.infer<typeof AgentToolContractManifestSchema>;

export function buildAgentToolContractManifest(): AgentToolContractManifest {
  return AgentToolContractManifestSchema.parse({
    schema_version: AGENT_TOOL_CONTRACT_VERSION,
    agent_count: 28,
    execution_stage_count: 29,
    tool_count: 18,
    agents: AGENT_IDS.map((agentId) => ({
      agent_id: agentId,
      layer: AGENT_LAYER_BY_ID[agentId],
      execution_stages: [...executionStagesFor(agentId)],
      allowed_tools: [...agentToolsFor(agentId)],
    })),
  });
}

export function validatePreparedCapability(
  bundleInput: unknown,
  capabilityInput: unknown,
): { bundle: AgentSnapshotBundle; capability: SignedAgentToolCapability } {
  const bundle = AgentSnapshotBundleSchema.parse(bundleInput);
  const capability = SignedAgentToolCapabilitySchema.parse(capabilityInput);
  const manifest = capability.manifest;
  if (
    manifest.agent_id !== bundle.agent_id ||
    manifest.stage !== bundle.stage ||
    manifest.as_of !== bundle.as_of ||
    manifest.candidate_scope_hash !== bundle.candidate_scope_hash ||
    manifest.snapshot_bundle_id !== bundle.snapshot_bundle_id ||
    manifest.snapshot_bundle_hash !== bundle.snapshot_bundle_hash ||
    [...manifest.allowed_tools].sort().join("\0") !==
      Object.keys(bundle.tool_payload_hashes).sort().join("\0")
  ) {
    throw new Error("capability/bundle binding mismatch");
  }
  return { bundle, capability };
}
