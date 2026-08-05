import {
  ALPHA_DISCOVERY_FIELD_NAMES,
  AUTONOMOUS_EXECUTION_FIELD_NAMES,
  CIO_FINAL_FIELD_NAMES,
  CIO_PROPOSAL_FIELD_NAMES,
  CRO_FIELD_NAMES,
} from "../decision/_schemas.js";
import {
  CENTRAL_BANK_FIELD_NAMES,
  CHINA_FIELD_NAMES,
  COMMODITIES_FIELD_NAMES,
  EU_ECONOMY_FIELD_NAMES,
  EURO_AREA_FINANCIAL_CONDITIONS_FIELD_NAMES,
  GEOPOLITICAL_FIELD_NAMES,
  INSTITUTIONAL_FLOW_FIELD_NAMES,
  MARKET_BREADTH_FIELD_NAMES,
  US_ECONOMY_FIELD_NAMES,
  US_FINANCIAL_CONDITIONS_FIELD_NAMES,
} from "../macro/_schemas.js";
import {
  RELATIONSHIP_MAPPER_FIELD_NAMES,
  STANDARD_SECTOR_FIELD_NAMES,
} from "../sector/_schemas.js";
import { SUPERINVESTOR_FIELD_NAMES } from "../superinvestor/_schemas.js";
import { AGENT_LAYER_BY_ID, AgentIdSchema, agentToolsFor } from "../tool_contract.js";
import type { Layer } from "./cohorts.js";
export const RUNTIME_AGENT_MANIFEST_VERSION = "runtime_agent_manifest_v5";

export const RUNTIME_AGENT_STAGE_IDS = [
  "agent_run",
  "alpha_discovery",
  "cio_proposal",
  "cro_review",
  "execution_feasibility",
  "cio_final",
] as const;

export type RuntimeAgentStageId = (typeof RUNTIME_AGENT_STAGE_IDS)[number];
export type RuntimeStageEnablement = "enabled";

export const RUNTIME_DAG_STAGE_IDS = [
  "cycle_input",
  "pre_stage_source_resolution",
  "agent_run",
  "alpha_discovery",
  "cio_proposal",
  "cro_review",
  "execution_feasibility",
  "cio_final",
  "shared_validation",
  "order_adapter",
] as const;

export type RuntimeDagStageId = (typeof RUNTIME_DAG_STAGE_IDS)[number];

export const RUNTIME_DAG_STAGE_ORDER: Readonly<Record<RuntimeDagStageId, number>> = {
  cycle_input: 0,
  pre_stage_source_resolution: 1,
  agent_run: 2,
  alpha_discovery: 3,
  cio_proposal: 4,
  cro_review: 5,
  execution_feasibility: 6,
  cio_final: 7,
  shared_validation: 8,
  order_adapter: 9,
};

export interface RuntimeAgentStageSpec {
  stage: RuntimeAgentStageId;
  enablement: RuntimeStageEnablement;
  outputSchemaRef: string;
  outputSchemaFields: ReadonlyArray<string>;
  maxRepairAttempts: 3;
  requiredSourceIds: ReadonlyArray<string>;
  producedSourceIds: ReadonlyArray<string>;
}

export interface RuntimeAgentSpec {
  agent: string;
  layer: Layer;
  promptIrAgentId: string;
  fieldNames: ReadonlyArray<string>;
  requiredTools: ReadonlyArray<string>;
  stages: ReadonlyArray<RuntimeAgentStageSpec>;
}

export interface RuntimeAgentManifestArtifact {
  schema_version: typeof RUNTIME_AGENT_MANIFEST_VERSION;
  runtime_agent_count: number;
  runtime_stage_count: number;
  canonical_l4_sequence: ReadonlyArray<RuntimeAgentStageId>;
  agents: ReadonlyArray<{
    agent: string;
    layer: Layer;
    prompt_ir_agent_id: string;
    required_tools: ReadonlyArray<string>;
    output_schema_fields: ReadonlyArray<string>;
    stages: ReadonlyArray<{
      stage: RuntimeAgentStageId;
      enablement: RuntimeStageEnablement;
      output_schema_ref: string;
      output_schema_fields: ReadonlyArray<string>;
      max_repair_attempts: 3;
      required_source_ids: ReadonlyArray<string>;
      produced_source_ids: ReadonlyArray<string>;
    }>;
  }>;
}

export const CANONICAL_L4_STAGE_SEQUENCE = [
  "alpha_discovery",
  "cio_proposal",
  "cro_review",
  "execution_feasibility",
  "cio_final",
] as const satisfies ReadonlyArray<RuntimeAgentStageId>;

function stageSpec(
  stage: RuntimeAgentStageId,
  outputSchemaRef: string,
  outputSchemaFields: ReadonlyArray<string>,
  requiredSourceIds: ReadonlyArray<string>,
  producedSourceIds: ReadonlyArray<string>,
): RuntimeAgentStageSpec {
  return {
    stage,
    enablement: "enabled",
    outputSchemaRef,
    outputSchemaFields,
    maxRepairAttempts: 3,
    requiredSourceIds,
    producedSourceIds,
  };
}

function stagesForAgent(
  layer: Layer,
  agent: string,
  promptIrAgentId: string,
  outputSchemaFields: ReadonlyArray<string>,
): ReadonlyArray<RuntimeAgentStageSpec> {
  if (layer !== "decision") {
    return [
      stageSpec(
        "agent_run",
        `${promptIrAgentId}.output.v1`,
        outputSchemaFields,
        [],
        ["upstream_agent_outputs"],
      ),
    ];
  }
  if (agent === "alpha_discovery") {
    return [
      stageSpec(
        "alpha_discovery",
        "decision.alpha_discovery.output.v1",
        outputSchemaFields,
        ["upstream_agent_outputs", "current_position_snapshot", "current_market_data"],
        ["upstream_agent_outputs"],
      ),
    ];
  }
  if (agent === "cro") {
    return [
      stageSpec(
        "cro_review",
        "decision.cro.review.v1",
        outputSchemaFields,
        [
          "candidate_target_state",
          "position_review_state",
          "current_position_snapshot",
          "current_market_data",
          "portfolio_exposure_state",
        ],
        ["cro_review_state"],
      ),
    ];
  }
  if (agent === "autonomous_execution") {
    return [
      stageSpec(
        "execution_feasibility",
        "decision.autonomous_execution.feasibility.v1",
        outputSchemaFields,
        [
          "candidate_target_state",
          "cro_review_state",
          "current_position_snapshot",
          "current_market_data",
          "execution_liquidity_state",
        ],
        ["execution_feasibility_state"],
      ),
    ];
  }
  if (agent === "cio") {
    return [
      stageSpec(
        "cio_proposal",
        "decision.cio.proposal.v1",
        CIO_PROPOSAL_FIELD_NAMES,
        [
          "upstream_agent_outputs",
          "current_position_snapshot",
          "current_market_data",
          "previous_target_state",
          "position_thesis_state",
        ],
        ["candidate_target_state", "position_review_state"],
      ),
      stageSpec(
        "cio_final",
        "decision.cio.final.v1",
        CIO_FINAL_FIELD_NAMES,
        [
          "candidate_target_state",
          "position_review_state",
          "cro_review_state",
          "execution_feasibility_state",
          "current_position_snapshot",
          "current_market_data",
        ],
        [],
      ),
    ];
  }
  throw new Error(`unsupported decision runtime agent: ${agent}`);
}

function runtimeSpec(
  layer: Layer,
  rawAgentId: string,
  fieldNames: ReadonlyArray<string>,
): RuntimeAgentSpec {
  const agentId = AgentIdSchema.parse(rawAgentId);
  if (AGENT_LAYER_BY_ID[agentId] !== layer) {
    throw new Error(`runtime layer mismatch for ${agentId}`);
  }
  const requiredTools = agentToolsFor(agentId);
  const promptIrAgentId = `${layer}.${agentId}`;
  return {
    agent: agentId,
    layer,
    promptIrAgentId,
    fieldNames,
    requiredTools,
    stages: stagesForAgent(layer, agentId, promptIrAgentId, fieldNames),
  };
}

export const RUNTIME_AGENT_SPECS: ReadonlyArray<RuntimeAgentSpec> = [
  runtimeSpec("macro", "china", CHINA_FIELD_NAMES),
  runtimeSpec("macro", "us_economy", US_ECONOMY_FIELD_NAMES),
  runtimeSpec("macro", "eu_economy", EU_ECONOMY_FIELD_NAMES),
  runtimeSpec("macro", "central_bank", CENTRAL_BANK_FIELD_NAMES),
  runtimeSpec("macro", "us_financial_conditions", US_FINANCIAL_CONDITIONS_FIELD_NAMES),
  runtimeSpec(
    "macro",
    "euro_area_financial_conditions",
    EURO_AREA_FINANCIAL_CONDITIONS_FIELD_NAMES,
  ),
  runtimeSpec("macro", "commodities", COMMODITIES_FIELD_NAMES),
  runtimeSpec("macro", "geopolitical", GEOPOLITICAL_FIELD_NAMES),
  runtimeSpec("macro", "market_breadth", MARKET_BREADTH_FIELD_NAMES),
  runtimeSpec("macro", "institutional_flow", INSTITUTIONAL_FLOW_FIELD_NAMES),
  runtimeSpec("sector", "semiconductor", STANDARD_SECTOR_FIELD_NAMES),
  runtimeSpec("sector", "technology", STANDARD_SECTOR_FIELD_NAMES),
  runtimeSpec("sector", "energy", STANDARD_SECTOR_FIELD_NAMES),
  runtimeSpec("sector", "biotech", STANDARD_SECTOR_FIELD_NAMES),
  runtimeSpec("sector", "consumer", STANDARD_SECTOR_FIELD_NAMES),
  runtimeSpec("sector", "industrials", STANDARD_SECTOR_FIELD_NAMES),
  runtimeSpec("sector", "real_estate_construction", STANDARD_SECTOR_FIELD_NAMES),
  runtimeSpec("sector", "financials", STANDARD_SECTOR_FIELD_NAMES),
  runtimeSpec("sector", "agriculture", STANDARD_SECTOR_FIELD_NAMES),
  runtimeSpec("sector", "relationship_mapper", RELATIONSHIP_MAPPER_FIELD_NAMES),
  runtimeSpec("superinvestor", "druckenmiller", SUPERINVESTOR_FIELD_NAMES),
  runtimeSpec("superinvestor", "munger", SUPERINVESTOR_FIELD_NAMES),
  runtimeSpec("superinvestor", "burry", SUPERINVESTOR_FIELD_NAMES),
  runtimeSpec("superinvestor", "ackman", SUPERINVESTOR_FIELD_NAMES),
  runtimeSpec("decision", "cro", CRO_FIELD_NAMES),
  runtimeSpec("decision", "alpha_discovery", ALPHA_DISCOVERY_FIELD_NAMES),
  runtimeSpec("decision", "autonomous_execution", AUTONOMOUS_EXECUTION_FIELD_NAMES),
  runtimeSpec("decision", "cio", CIO_FINAL_FIELD_NAMES),
];

export const RUNTIME_AGENT_SPEC_BY_AGENT: ReadonlyMap<string, RuntimeAgentSpec> = new Map(
  RUNTIME_AGENT_SPECS.map((spec) => [spec.agent, spec]),
);

export const RUNTIME_AGENT_STAGE_SPECS: ReadonlyArray<
  RuntimeAgentStageSpec & Pick<RuntimeAgentSpec, "agent" | "layer" | "promptIrAgentId">
> = RUNTIME_AGENT_SPECS.flatMap((spec) =>
  spec.stages.map((stage) => ({
    agent: spec.agent,
    layer: spec.layer,
    promptIrAgentId: spec.promptIrAgentId,
    ...stage,
  })),
);

export function runtimeAgentStageKey(agent: string, stage: RuntimeAgentStageId): string {
  return `${agent}:${stage}`;
}

export const RUNTIME_AGENT_STAGE_SPEC_BY_KEY = new Map(
  RUNTIME_AGENT_STAGE_SPECS.map((spec) => [runtimeAgentStageKey(spec.agent, spec.stage), spec]),
);

export function buildRuntimeAgentManifestArtifact(
  specs: ReadonlyArray<RuntimeAgentSpec> = RUNTIME_AGENT_SPECS,
): RuntimeAgentManifestArtifact {
  return {
    schema_version: RUNTIME_AGENT_MANIFEST_VERSION,
    runtime_agent_count: specs.length,
    runtime_stage_count: specs.reduce((count, spec) => count + spec.stages.length, 0),
    canonical_l4_sequence: [...CANONICAL_L4_STAGE_SEQUENCE],
    agents: specs.map((spec) => ({
      agent: spec.agent,
      layer: spec.layer,
      prompt_ir_agent_id: spec.promptIrAgentId,
      required_tools: [...spec.requiredTools],
      output_schema_fields: [...spec.fieldNames],
      stages: spec.stages.map((stage) => ({
        stage: stage.stage,
        enablement: stage.enablement,
        output_schema_ref: stage.outputSchemaRef,
        output_schema_fields: [...stage.outputSchemaFields],
        max_repair_attempts: stage.maxRepairAttempts,
        required_source_ids: [...stage.requiredSourceIds],
        produced_source_ids: [...stage.producedSourceIds],
      })),
    })),
  };
}

export function renderRuntimeAgentManifestArtifact(
  artifact: RuntimeAgentManifestArtifact = buildRuntimeAgentManifestArtifact(),
): string {
  return `${JSON.stringify(artifact, null, 2)}\n`;
}

export function validateRuntimeAgentManifestArtifact(
  artifact: RuntimeAgentManifestArtifact,
): string[] {
  const reasons: string[] = [];
  if (artifact.schema_version !== RUNTIME_AGENT_MANIFEST_VERSION) {
    reasons.push(`runtime_manifest_schema_version_mismatch:${artifact.schema_version}`);
  }
  if (artifact.runtime_agent_count !== RUNTIME_AGENT_SPECS.length) {
    reasons.push(
      `runtime_manifest_agent_count_mismatch:${artifact.runtime_agent_count}:expected:${RUNTIME_AGENT_SPECS.length}`,
    );
  }
  const stageCount = artifact.agents.reduce((count, spec) => count + spec.stages.length, 0);
  if (artifact.runtime_stage_count !== stageCount) {
    reasons.push(
      `runtime_manifest_stage_count_mismatch:${artifact.runtime_stage_count}:expected:${stageCount}`,
    );
  }
  if (artifact.canonical_l4_sequence.join(",") !== CANONICAL_L4_STAGE_SEQUENCE.join(",")) {
    reasons.push("runtime_manifest_l4_sequence_mismatch");
  }
  const seenStages = new Set<string>();
  const runtimeSpecByAgent = new Map(RUNTIME_AGENT_SPECS.map((spec) => [spec.agent, spec]));
  for (const agent of artifact.agents) {
    const runtimeSpec = runtimeSpecByAgent.get(agent.agent);
    if (!runtimeSpec) {
      reasons.push(`runtime_manifest_agent_unknown:${agent.agent}`);
      continue;
    }
    const expectedAgentFields = new Set(
      runtimeSpec.stages.flatMap((stage) => [...stage.outputSchemaFields]),
    );
    if (new Set(agent.output_schema_fields).size !== agent.output_schema_fields.length) {
      reasons.push(`runtime_manifest_agent_output_fields_duplicate:${agent.agent}`);
    }
    if (
      [...new Set(agent.output_schema_fields)].sort().join("\0") !==
      [...expectedAgentFields].sort().join("\0")
    ) {
      reasons.push(`runtime_manifest_agent_output_fields_mismatch:${agent.agent}`);
    }
    for (const stage of agent.stages) {
      const key = runtimeAgentStageKey(agent.agent, stage.stage);
      if (seenStages.has(key)) reasons.push(`runtime_manifest_duplicate_stage:${key}`);
      seenStages.add(key);
      if (!stage.output_schema_ref) reasons.push(`runtime_manifest_output_schema_missing:${key}`);
      const expectedStage = runtimeSpec.stages.find((row) => row.stage === stage.stage);
      if (new Set(stage.output_schema_fields).size !== stage.output_schema_fields.length) {
        reasons.push(`runtime_manifest_stage_output_fields_duplicate:${key}`);
      }
      if (!expectedStage) {
        reasons.push(`runtime_manifest_stage_unknown:${key}`);
      } else if (
        [...new Set(stage.output_schema_fields)].sort().join("\0") !==
        [...expectedStage.outputSchemaFields].sort().join("\0")
      ) {
        reasons.push(`runtime_manifest_stage_output_fields_mismatch:${key}`);
      }
      if (stage.max_repair_attempts !== 3)
        reasons.push(`runtime_manifest_repair_budget_invalid:${key}`);
    }
  }
  const cio = artifact.agents.find((agent) => agent.agent === "cio");
  const cioStages = new Set(cio?.stages.map((stage) => stage.stage) ?? []);
  for (const stage of ["cio_proposal", "cio_final"] as const) {
    if (!cioStages.has(stage)) reasons.push(`runtime_manifest_cio_stage_missing:${stage}`);
  }
  const proposal = cio?.stages.find((stage) => stage.stage === "cio_proposal");
  if (proposal?.required_source_ids.includes("candidate_target_state")) {
    reasons.push("runtime_manifest_cio_proposal_self_loop:candidate_target_state");
  }
  return reasons;
}
