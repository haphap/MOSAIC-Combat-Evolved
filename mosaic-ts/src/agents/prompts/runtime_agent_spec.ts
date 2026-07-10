import { alphaDiscoverySpec } from "../decision/alpha_discovery.js";
import { autonomousExecutionSpec } from "../decision/autonomous_execution.js";
import { cioSpec } from "../decision/cio.js";
import { croSpec } from "../decision/cro.js";
import { centralBankSpec } from "../macro/central_bank.js";
import { chinaSpec } from "../macro/china.js";
import { commoditiesSpec } from "../macro/commodities.js";
import { dollarSpec } from "../macro/dollar.js";
import { emergingMarketsSpec } from "../macro/emerging_markets.js";
import { geopoliticalSpec } from "../macro/geopolitical.js";
import { institutionalFlowSpec } from "../macro/institutional_flow.js";
import { newsSentimentSpec } from "../macro/news_sentiment.js";
import { volatilitySpec } from "../macro/volatility.js";
import { yieldCurveSpec } from "../macro/yield_curve.js";
import { biotechSpec } from "../sector/biotech.js";
import { consumerSpec } from "../sector/consumer.js";
import { energySpec } from "../sector/energy.js";
import { financialsSpec } from "../sector/financials.js";
import { industrialsSpec } from "../sector/industrials.js";
import { relationshipMapperSpec } from "../sector/relationship_mapper.js";
import { semiconductorSpec } from "../sector/semiconductor.js";
import { ackmanSpec } from "../superinvestor/ackman.js";
import { burrySpec } from "../superinvestor/burry.js";
import { druckenmillerSpec } from "../superinvestor/druckenmiller.js";
import { mungerSpec } from "../superinvestor/munger.js";
import type { Layer } from "./cohorts.js";

export const RUNTIME_AGENT_MANIFEST_VERSION = "runtime_agent_manifest_v1";

export const RUNTIME_AGENT_STAGE_IDS = [
  "agent_run",
  "alpha_discovery",
  "cio_proposal",
  "cro_review",
  "execution_feasibility",
  "cio_final",
] as const;

export type RuntimeAgentStageId = (typeof RUNTIME_AGENT_STAGE_IDS)[number];
export type RuntimeStageEnablement = "declared" | "legacy" | "enabled";

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
  fallbackFactoryId: string;
  fallbackFactoryVersion: string;
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
      fallback_factory_id: string;
      fallback_factory_version: string;
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
  requiredSourceIds: ReadonlyArray<string>,
  producedSourceIds: ReadonlyArray<string>,
  enablement: RuntimeStageEnablement,
  promptIrAgentId: string,
): RuntimeAgentStageSpec {
  return {
    stage,
    enablement,
    outputSchemaRef,
    fallbackFactoryId: `${promptIrAgentId}.${stage}.fallback`,
    fallbackFactoryVersion: "1",
    requiredSourceIds,
    producedSourceIds,
  };
}

function stagesForAgent(
  layer: Layer,
  agent: string,
  promptIrAgentId: string,
): ReadonlyArray<RuntimeAgentStageSpec> {
  if (layer !== "decision") {
    return [
      stageSpec(
        "agent_run",
        `${promptIrAgentId}.output.v1`,
        [],
        ["upstream_agent_outputs"],
        "legacy",
        promptIrAgentId,
      ),
    ];
  }
  if (agent === "alpha_discovery") {
    return [
      stageSpec(
        "alpha_discovery",
        "decision.alpha_discovery.output.v1",
        ["upstream_agent_outputs", "current_position_snapshot", "current_market_data"],
        ["upstream_agent_outputs"],
        "enabled",
        promptIrAgentId,
      ),
    ];
  }
  if (agent === "cro") {
    return [
      stageSpec(
        "cro_review",
        "decision.cro.review.v1",
        [
          "candidate_target_state",
          "position_review_state",
          "current_position_snapshot",
          "current_market_data",
          "portfolio_exposure_state",
        ],
        ["cro_review_state"],
        "enabled",
        promptIrAgentId,
      ),
    ];
  }
  if (agent === "autonomous_execution") {
    return [
      stageSpec(
        "execution_feasibility",
        "decision.autonomous_execution.feasibility.v1",
        [
          "candidate_target_state",
          "cro_review_state",
          "current_position_snapshot",
          "current_market_data",
          "execution_liquidity_state",
        ],
        ["execution_feasibility_state"],
        "enabled",
        promptIrAgentId,
      ),
    ];
  }
  if (agent === "cio") {
    return [
      stageSpec(
        "cio_proposal",
        "decision.cio.proposal.v1",
        [
          "upstream_agent_outputs",
          "current_position_snapshot",
          "current_market_data",
          "previous_target_state",
          "position_thesis_state",
        ],
        ["candidate_target_state", "position_review_state"],
        "enabled",
        promptIrAgentId,
      ),
      stageSpec(
        "cio_final",
        "decision.cio.final.v1",
        [
          "candidate_target_state",
          "position_review_state",
          "cro_review_state",
          "execution_feasibility_state",
          "current_position_snapshot",
          "current_market_data",
        ],
        [],
        "enabled",
        promptIrAgentId,
      ),
    ];
  }
  throw new Error(`unsupported decision runtime agent: ${agent}`);
}

function runtimeSpec(
  layer: Layer,
  spec: {
    agentId: string;
    fieldNames: ReadonlyArray<string>;
    requiredTools?: ReadonlyArray<string>;
  },
): RuntimeAgentSpec {
  const promptIrAgentId = `${layer}.${spec.agentId}`;
  return {
    agent: spec.agentId,
    layer,
    promptIrAgentId,
    fieldNames: spec.fieldNames,
    requiredTools: spec.requiredTools ?? [],
    stages: stagesForAgent(layer, spec.agentId, promptIrAgentId),
  };
}

export const RUNTIME_AGENT_SPECS: ReadonlyArray<RuntimeAgentSpec> = [
  runtimeSpec("macro", centralBankSpec),
  runtimeSpec("macro", geopoliticalSpec),
  runtimeSpec("macro", chinaSpec),
  runtimeSpec("macro", dollarSpec),
  runtimeSpec("macro", yieldCurveSpec),
  runtimeSpec("macro", commoditiesSpec),
  runtimeSpec("macro", volatilitySpec),
  runtimeSpec("macro", emergingMarketsSpec),
  runtimeSpec("macro", newsSentimentSpec),
  runtimeSpec("macro", institutionalFlowSpec),
  runtimeSpec("sector", semiconductorSpec),
  runtimeSpec("sector", energySpec),
  runtimeSpec("sector", biotechSpec),
  runtimeSpec("sector", consumerSpec),
  runtimeSpec("sector", industrialsSpec),
  runtimeSpec("sector", financialsSpec),
  runtimeSpec("sector", relationshipMapperSpec),
  runtimeSpec("superinvestor", druckenmillerSpec),
  runtimeSpec("superinvestor", mungerSpec),
  runtimeSpec("superinvestor", burrySpec),
  runtimeSpec("superinvestor", ackmanSpec),
  runtimeSpec("decision", croSpec),
  runtimeSpec("decision", alphaDiscoverySpec),
  runtimeSpec("decision", autonomousExecutionSpec),
  runtimeSpec("decision", cioSpec),
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
        fallback_factory_id: stage.fallbackFactoryId,
        fallback_factory_version: stage.fallbackFactoryVersion,
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
  for (const agent of artifact.agents) {
    for (const stage of agent.stages) {
      const key = runtimeAgentStageKey(agent.agent, stage.stage);
      if (seenStages.has(key)) reasons.push(`runtime_manifest_duplicate_stage:${key}`);
      seenStages.add(key);
      if (!stage.output_schema_ref) reasons.push(`runtime_manifest_output_schema_missing:${key}`);
      if (!stage.fallback_factory_id || !stage.fallback_factory_version) {
        reasons.push(`runtime_manifest_fallback_factory_missing:${key}`);
      }
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
