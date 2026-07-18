import { KNOT_RUNTIME_CONTRACT_MANIFEST } from "../../autoresearch/knot_contract.js";
import { alphaDiscoverySpec } from "../decision/alpha_discovery.js";
import { autonomousExecutionSpec } from "../decision/autonomous_execution.js";
import { cioSpec } from "../decision/cio.js";
import { croSpec } from "../decision/cro.js";
import { centralBankSpec } from "../macro/central_bank.js";
import { chinaSpec } from "../macro/china.js";
import { commoditiesSpec } from "../macro/commodities.js";
import { euEconomySpec } from "../macro/eu_economy.js";
import { euroAreaFinancialConditionsSpec } from "../macro/euro_area_financial_conditions.js";
import { geopoliticalSpec } from "../macro/geopolitical.js";
import { institutionalFlowSpec } from "../macro/institutional_flow.js";
import { marketBreadthSpec } from "../macro/market_breadth.js";
import { usEconomySpec } from "../macro/us_economy.js";
import { usFinancialConditionsSpec } from "../macro/us_financial_conditions.js";
import { agricultureSpec } from "../sector/agriculture.js";
import { biotechSpec } from "../sector/biotech.js";
import { consumerSpec } from "../sector/consumer.js";
import { energySpec } from "../sector/energy.js";
import { financialsSpec } from "../sector/financials.js";
import { industrialsSpec } from "../sector/industrials.js";
import { realEstateConstructionSpec } from "../sector/real_estate_construction.js";
import { relationshipMapperSpec } from "../sector/relationship_mapper.js";
import { semiconductorSpec } from "../sector/semiconductor.js";
import { technologySpec } from "../sector/technology.js";
import { ackmanSpec } from "../superinvestor/ackman.js";
import { burrySpec } from "../superinvestor/burry.js";
import { druckenmillerSpec } from "../superinvestor/druckenmiller.js";
import { mungerSpec } from "../superinvestor/munger.js";
import { AGENT_LAYER_BY_ID, AgentIdSchema, agentToolsFor } from "../tool_contract.js";
import type { Layer } from "./cohorts.js";
import {
  configuredRuntimeResearchKnobsCohorts,
  configuredRuntimeResearchKnobsStageKeys,
  DEFAULT_RUNTIME_RESEARCH_KNOBS_COHORT,
  runtimeResearchKnobsStageEnablement,
} from "./runtime_stage_enablement.js";

export const RUNTIME_AGENT_MANIFEST_VERSION = "runtime_agent_manifest_v3";

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
  default_cohort: string;
  research_knobs_cohort_enablement: ReadonlyArray<{
    cohort: string;
    enabled_agent_stages: ReadonlyArray<string>;
    legacy_agent_stages: ReadonlyArray<string>;
  }>;
  canonical_l4_sequence: ReadonlyArray<RuntimeAgentStageId>;
  knot_runtime_contract_ref: {
    knot_runtime_contract_manifest_id: string;
    knot_runtime_contract_manifest_version: string;
    knot_runtime_contract_manifest_hash: string;
    research_score_contract_id: string;
    research_score_contract_version: string;
    research_score_contract_hash: string;
    scheduler_contract_id: string;
    scheduler_contract_version: string;
    scheduler_contract_hash: string;
  };
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
  requiredSourceIds: ReadonlyArray<string>,
  producedSourceIds: ReadonlyArray<string>,
  enablement: RuntimeStageEnablement,
  _promptIrAgentId: string,
): RuntimeAgentStageSpec {
  return {
    stage,
    enablement,
    outputSchemaRef,
    maxRepairAttempts: 3,
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
        runtimeResearchKnobsStageEnablement(
          DEFAULT_RUNTIME_RESEARCH_KNOBS_COHORT,
          agent,
          "agent_run",
        ),
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
        runtimeResearchKnobsStageEnablement(
          DEFAULT_RUNTIME_RESEARCH_KNOBS_COHORT,
          agent,
          "alpha_discovery",
        ),
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
        runtimeResearchKnobsStageEnablement(
          DEFAULT_RUNTIME_RESEARCH_KNOBS_COHORT,
          agent,
          "cro_review",
        ),
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
        runtimeResearchKnobsStageEnablement(
          DEFAULT_RUNTIME_RESEARCH_KNOBS_COHORT,
          agent,
          "execution_feasibility",
        ),
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
        runtimeResearchKnobsStageEnablement(
          DEFAULT_RUNTIME_RESEARCH_KNOBS_COHORT,
          agent,
          "cio_proposal",
        ),
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
        runtimeResearchKnobsStageEnablement(
          DEFAULT_RUNTIME_RESEARCH_KNOBS_COHORT,
          agent,
          "cio_final",
        ),
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
  const agentId = AgentIdSchema.parse(spec.agentId);
  if (AGENT_LAYER_BY_ID[agentId] !== layer) {
    throw new Error(`runtime layer mismatch for ${agentId}`);
  }
  const requiredTools = agentToolsFor(agentId);
  if (
    spec.requiredTools &&
    [...spec.requiredTools].sort().join("\0") !== [...requiredTools].sort().join("\0")
  ) {
    throw new Error(`runtime tool contract drift for ${agentId}`);
  }
  const promptIrAgentId = `${layer}.${spec.agentId}`;
  return {
    agent: spec.agentId,
    layer,
    promptIrAgentId,
    fieldNames: spec.fieldNames,
    requiredTools,
    stages: stagesForAgent(layer, spec.agentId, promptIrAgentId),
  };
}

export const RUNTIME_AGENT_SPECS: ReadonlyArray<RuntimeAgentSpec> = [
  runtimeSpec("macro", chinaSpec),
  runtimeSpec("macro", usEconomySpec),
  runtimeSpec("macro", euEconomySpec),
  runtimeSpec("macro", centralBankSpec),
  runtimeSpec("macro", usFinancialConditionsSpec),
  runtimeSpec("macro", euroAreaFinancialConditionsSpec),
  runtimeSpec("macro", commoditiesSpec),
  runtimeSpec("macro", geopoliticalSpec),
  runtimeSpec("macro", marketBreadthSpec),
  runtimeSpec("macro", institutionalFlowSpec),
  runtimeSpec("sector", semiconductorSpec),
  runtimeSpec("sector", technologySpec),
  runtimeSpec("sector", energySpec),
  runtimeSpec("sector", biotechSpec),
  runtimeSpec("sector", consumerSpec),
  runtimeSpec("sector", industrialsSpec),
  runtimeSpec("sector", realEstateConstructionSpec),
  runtimeSpec("sector", financialsSpec),
  runtimeSpec("sector", agricultureSpec),
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
  const allStageKeys = specs.flatMap((spec) =>
    spec.stages.map((stage) => runtimeAgentStageKey(spec.agent, stage.stage)),
  );
  return {
    schema_version: RUNTIME_AGENT_MANIFEST_VERSION,
    runtime_agent_count: specs.length,
    runtime_stage_count: specs.reduce((count, spec) => count + spec.stages.length, 0),
    default_cohort: DEFAULT_RUNTIME_RESEARCH_KNOBS_COHORT,
    research_knobs_cohort_enablement: configuredRuntimeResearchKnobsCohorts().map((cohort) => {
      const enabled = configuredRuntimeResearchKnobsStageKeys(cohort);
      return {
        cohort,
        enabled_agent_stages: allStageKeys.filter((key) => enabled.has(key)),
        legacy_agent_stages: allStageKeys.filter((key) => !enabled.has(key)),
      };
    }),
    canonical_l4_sequence: [...CANONICAL_L4_STAGE_SEQUENCE],
    knot_runtime_contract_ref: {
      knot_runtime_contract_manifest_id:
        KNOT_RUNTIME_CONTRACT_MANIFEST.knot_runtime_contract_manifest_id,
      knot_runtime_contract_manifest_version:
        KNOT_RUNTIME_CONTRACT_MANIFEST.knot_runtime_contract_manifest_version,
      knot_runtime_contract_manifest_hash:
        KNOT_RUNTIME_CONTRACT_MANIFEST.knot_runtime_contract_manifest_hash,
      research_score_contract_id:
        KNOT_RUNTIME_CONTRACT_MANIFEST.research_score_contract.research_score_contract_id,
      research_score_contract_version:
        KNOT_RUNTIME_CONTRACT_MANIFEST.research_score_contract.research_score_contract_version,
      research_score_contract_hash:
        KNOT_RUNTIME_CONTRACT_MANIFEST.research_score_contract.research_score_contract_hash,
      scheduler_contract_id:
        KNOT_RUNTIME_CONTRACT_MANIFEST.scheduler_contract.scheduler_contract_id,
      scheduler_contract_version:
        KNOT_RUNTIME_CONTRACT_MANIFEST.scheduler_contract.scheduler_contract_version,
      scheduler_contract_hash:
        KNOT_RUNTIME_CONTRACT_MANIFEST.scheduler_contract.scheduler_contract_hash,
    },
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
  if (artifact.default_cohort !== DEFAULT_RUNTIME_RESEARCH_KNOBS_COHORT) {
    reasons.push(
      `runtime_manifest_default_cohort_mismatch:${artifact.default_cohort}:expected:${DEFAULT_RUNTIME_RESEARCH_KNOBS_COHORT}`,
    );
  }
  const seenStages = new Set<string>();
  for (const agent of artifact.agents) {
    for (const stage of agent.stages) {
      const key = runtimeAgentStageKey(agent.agent, stage.stage);
      if (seenStages.has(key)) reasons.push(`runtime_manifest_duplicate_stage:${key}`);
      seenStages.add(key);
      if (!stage.output_schema_ref) reasons.push(`runtime_manifest_output_schema_missing:${key}`);
      if (stage.max_repair_attempts !== 3)
        reasons.push(`runtime_manifest_repair_budget_invalid:${key}`);
    }
  }
  const seenCohorts = new Set<string>();
  for (const cohort of artifact.research_knobs_cohort_enablement) {
    if (seenCohorts.has(cohort.cohort)) {
      reasons.push(`runtime_manifest_duplicate_cohort:${cohort.cohort}`);
    }
    seenCohorts.add(cohort.cohort);
    const expectedEnabled = configuredRuntimeResearchKnobsStageKeys(cohort.cohort);
    const declaredEnabled = new Set(cohort.enabled_agent_stages);
    const declaredLegacy = new Set(cohort.legacy_agent_stages);
    for (const key of declaredEnabled) {
      if (!seenStages.has(key))
        reasons.push(`runtime_manifest_enabled_stage_unknown:${cohort.cohort}:${key}`);
      if (declaredLegacy.has(key)) {
        reasons.push(`runtime_manifest_stage_enabled_and_legacy:${cohort.cohort}:${key}`);
      }
    }
    for (const key of seenStages) {
      if (declaredEnabled.has(key) === declaredLegacy.has(key)) {
        reasons.push(`runtime_manifest_cohort_stage_partition_invalid:${cohort.cohort}:${key}`);
      }
      if (declaredEnabled.has(key) !== expectedEnabled.has(key)) {
        reasons.push(`runtime_manifest_cohort_enablement_drift:${cohort.cohort}:${key}`);
      }
    }
  }
  for (const cohort of configuredRuntimeResearchKnobsCohorts()) {
    if (!seenCohorts.has(cohort)) reasons.push(`runtime_manifest_cohort_missing:${cohort}`);
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
