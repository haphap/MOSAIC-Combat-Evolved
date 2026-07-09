import { existsSync } from "node:fs";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { z } from "zod";
import { normalizePromptsRoot } from "./cohorts.js";
import { registeredMetricIdsForTool } from "./domain_knob_catalog.js";
import type { RuntimeAgentSpec } from "./runtime_agent_spec.js";

const PROMPT_IR_VERSION = "prompt_ir_runtime_contract_v1";

const EvolutionTargetsSchema = z
  .object({
    allowed_paths: z.array(z.string().min(1)),
    forbidden_paths: z.array(z.string().min(1)),
  })
  .strict();

const ToolRequirementSchema = z
  .object({
    name: z.string().min(1),
    freshness_max_days: z.number().int().min(0),
    required: z.boolean(),
    metric_ids: z.array(z.string().min(1)),
    metric_candidate_ids: z.array(z.string().min(1)),
    analysis_recipe_ids: z.array(z.string().min(1)),
    pit_required_for_backtest: z.boolean(),
    fallback_confidence_cap: z.number().min(0).max(1).nullable(),
    lineage: z.record(z.string(), z.unknown()),
  })
  .strict();

const PromptIrContractSchema = z
  .object({
    schema_version: z.literal(PROMPT_IR_VERSION),
    agent_id: z.string().min(1),
    layer: z.enum(["macro", "sector", "superinvestor", "decision"]),
    cohort: z.string().min(1),
    prompt_version: z.string().min(1),
    role_contract: z
      .object({
        responsibility: z.string().min(1),
        may_decide: z.array(z.string().min(1)),
        must_not_decide: z.array(z.string().min(1)),
      })
      .strict(),
    required_tools: z.array(ToolRequirementSchema),
    fallback_tools: z.array(
      z
        .object({
          name: z.string().min(1),
          confidence_cap: z.number().min(0).max(1),
        })
        .strict(),
    ),
    research_rule_pack_refs: z.array(z.string().min(1)),
    confidence_policy_ref: z.string().min(1),
    rule_aggregation_policy_ref: z.string().min(1),
    output_schema_ref: z.string().min(1),
    output_schema_fields: z.array(z.string().min(1)),
    progress_event_schema_ref: z.string().min(1),
    handoff_schema_ref: z.string().min(1),
    evolution_targets: EvolutionTargetsSchema,
    guardrails: z.array(z.string().min(1)),
    shared_contract_refs: z.array(z.string().min(1)),
    status: z
      .object({
        promotion_state: z.string().min(1),
        production_allowed: z.boolean(),
        manual_gold_set_required: z.boolean(),
        source_license_review_required: z.boolean(),
        lockbox_required: z.boolean(),
      })
      .strict(),
  })
  .strict();

export type PromptIrContract = z.infer<typeof PromptIrContractSchema>;

const DEFAULT_ALLOWED_EVOLUTION_PATHS = [
  "/rule_packs/*/rules/*/learnable_parameters/*/value",
  "/rule_packs/*/rules/*/confidence_policy/*/cap",
  "/rule_packs/*/rules/*/confidence_policy/*",
  "/rule_packs/*/rules/*/predicate/*",
  "/research_weighting/source_profiles/*/weight_policy",
  "/research_weighting/viewpoint_profiles/*/weight_policy",
  "/research_weighting/method_profiles/*/priority_policy",
  "/weighted_research_retriever/ranking_weights/*",
  "/weighted_research_retriever/diversity_policy/*",
  "/metric_candidate_registry/*/aliases",
  "/metric_candidate_registry/*/priority_bucket",
  "/method_pattern_registry/*/status",
  "/tool_gap_registry/*/priority_bucket",
  "/data_acquisition_proposals/*/status",
  "/tool_design_proposals/*/status",
  "/analysis_recipe_registry/*/runtime_mode",
  "/analysis_recipe_registry/*/validation_status",
  "/prompt_ir/tool_contracts/candidate_tools/*",
  "/rule_packs/*/research_prior",
] as const;

const DEFAULT_FORBIDDEN_EVOLUTION_PATHS = [
  "/role_contract",
  "/tool_contract/required_tools",
  "/prompt_ir/tool_contracts/required_tools",
  "/output_schema_ref",
  "/evidence_schema",
  "/guardrails",
  "/compliance_gates",
  "/validation_acceptance_standards",
  "/sector_score",
  "/portfolio_sizing",
  "/action_policy",
  "/prompt_ir/action_policy",
  "/report_intelligence/forecast_claims/*/claim_provenance",
  "/report_intelligence/analytical_footprints/*/source_grounded",
  "/source_claims/*/claim_provenance",
  "/evidence_ledger/current_tool_data",
] as const;

export function promptIrRepoRootFromPromptsRoot(promptsRoot: string): string {
  return dirname(dirname(normalizePromptsRoot(promptsRoot)));
}

export function promptIrPathForSpec(opts: {
  privatePromptsRoot: string;
  spec: RuntimeAgentSpec;
}): string {
  return join(
    promptIrRepoRootFromPromptsRoot(opts.privatePromptsRoot),
    "prompt_ir",
    `${opts.spec.promptIrAgentId}.json`,
  );
}

export async function readPromptIrContractFile(path: string): Promise<PromptIrContract | null> {
  if (!existsSync(path)) return null;
  const raw = await readFile(path, "utf-8");
  return PromptIrContractSchema.parse(JSON.parse(raw) as unknown);
}

export async function writePromptIrContractFile(
  path: string,
  contract: PromptIrContract,
): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  const tmpPath = `${path}.tmp-${process.pid}-${Date.now()}`;
  await writeFile(tmpPath, renderPromptIrContract(contract), "utf-8");
  await rename(tmpPath, path);
}

export function buildPromptIrContract(spec: RuntimeAgentSpec, cohort: string): PromptIrContract {
  return {
    schema_version: PROMPT_IR_VERSION,
    agent_id: spec.promptIrAgentId,
    layer: spec.layer,
    cohort,
    prompt_version: "0.4.0-research-knobs",
    role_contract: roleContractForSpec(spec),
    required_tools: spec.requiredTools.map((tool) => ({
      name: tool,
      freshness_max_days: tool === "get_rke_research_context" ? 30 : 1,
      required: true,
      metric_ids: [...registeredMetricIdsForTool(tool)].sort(),
      metric_candidate_ids: [],
      analysis_recipe_ids: [],
      pit_required_for_backtest: true,
      fallback_confidence_cap: tool === "get_rke_research_context" ? null : 0.6,
      lineage: {},
    })),
    fallback_tools: spec.requiredTools
      .filter((tool) => tool !== "get_rke_research_context")
      .map((tool) => ({ name: `${tool}:fallback`, confidence_cap: 0.6 })),
    research_rule_pack_refs: [`${spec.layer}.${spec.agent}.runtime.v1`],
    confidence_policy_ref: "confidence_policy.v1",
    rule_aggregation_policy_ref: "rule_aggregation_policy.v1",
    output_schema_ref: `agent_output_schema.${spec.promptIrAgentId}.v1`,
    output_schema_fields: [...spec.fieldNames].sort(),
    progress_event_schema_ref: "progress_event.v1",
    handoff_schema_ref: "downstream_handoff.v1",
    evolution_targets: {
      allowed_paths: [...DEFAULT_ALLOWED_EVOLUTION_PATHS],
      forbidden_paths: [...DEFAULT_FORBIDDEN_EVOLUTION_PATHS],
    },
    guardrails: [
      "research_reports_are_prior_not_signal",
      "research_only_no_trade",
      "no_direct_production_promotion",
      "production_blocked_until_manual_gold_license_and_lockbox_gates_pass",
    ],
    shared_contract_refs: [
      "rke_runtime_contract",
      "confidence_policy.v1",
      "rule_aggregation_policy.v1",
      "research_knobs_v1",
      "domain_knob_catalog_v1",
    ],
    status: {
      promotion_state: "paper_trading",
      production_allowed: false,
      manual_gold_set_required: true,
      source_license_review_required: true,
      lockbox_required: true,
    },
  };
}

export function renderPromptIrContract(contract: PromptIrContract): string {
  return `${JSON.stringify(canonicalPromptIrContract(contract), null, 2)}\n`;
}

export function validatePromptIrContractForSpec(
  contract: PromptIrContract,
  spec: RuntimeAgentSpec,
  cohort: string,
): string[] {
  const reasons: string[] = [];
  if (contract.schema_version !== PROMPT_IR_VERSION) {
    reasons.push(`prompt_ir_schema_version_mismatch:${contract.schema_version}`);
  }
  if (contract.agent_id !== spec.promptIrAgentId) {
    reasons.push(`prompt_ir_agent_mismatch:${contract.agent_id}:expected:${spec.promptIrAgentId}`);
  }
  if (contract.layer !== spec.layer) {
    reasons.push(`prompt_ir_layer_mismatch:${contract.layer}:expected:${spec.layer}`);
  }
  if (contract.cohort !== cohort) {
    reasons.push(`prompt_ir_cohort_mismatch:${contract.cohort}:expected:${cohort}`);
  }
  const promptIrTools = contract.required_tools.map((tool) => tool.name).sort();
  const runtimeTools = [...spec.requiredTools].sort();
  if (promptIrTools.join(",") !== runtimeTools.join(",")) {
    reasons.push(
      `prompt_ir_required_tools_mismatch:${promptIrTools.join(",")}:expected:${runtimeTools.join(",")}`,
    );
  }
  const promptIrFields = [...contract.output_schema_fields].sort();
  const runtimeFields = [...spec.fieldNames].sort();
  if (promptIrFields.join(",") !== runtimeFields.join(",")) {
    reasons.push("prompt_ir_output_schema_fields_mismatch");
  }
  for (const tool of contract.required_tools) {
    const expectedMetrics = registeredMetricIdsForTool(tool.name);
    for (const metric of tool.metric_ids) {
      if (!expectedMetrics.has(metric)) {
        reasons.push(`prompt_ir_metric_not_registered:${tool.name}:${metric}`);
      }
    }
    if (tool.required !== true) {
      reasons.push(`prompt_ir_tool_not_required:${tool.name}`);
    }
    if (!tool.pit_required_for_backtest) {
      reasons.push(`prompt_ir_tool_missing_pit_requirement:${tool.name}`);
    }
  }
  if (!contract.guardrails.includes("research_reports_are_prior_not_signal")) {
    reasons.push("prompt_ir_missing_rke_prior_guardrail");
  }
  if (contract.status.production_allowed) {
    reasons.push("prompt_ir_production_allowed_without_gate");
  }
  for (const forbidden of contract.evolution_targets.forbidden_paths) {
    if (contract.evolution_targets.allowed_paths.includes(forbidden)) {
      reasons.push(`prompt_ir_evolution_path_both_allowed_and_forbidden:${forbidden}`);
    }
  }
  return reasons;
}

function roleContractForSpec(spec: RuntimeAgentSpec): PromptIrContract["role_contract"] {
  return {
    responsibility: `Generate ${spec.promptIrAgentId} research output for the MOSAIC daily cycle.`,
    may_decide: spec.fieldNames.filter(
      (field) =>
        ![
          "agent",
          "confidence",
          "declared_knob_influence_ids",
          "declared_influence_rationale",
        ].includes(field),
    ),
    must_not_decide:
      spec.layer === "decision"
        ? ["modify_prompt_governance", "bypass_risk_guardrails"]
        : ["final_portfolio_sizing", "single_stock_trade_authorization"],
  };
}

function canonicalPromptIrContract(contract: PromptIrContract): PromptIrContract {
  return {
    schema_version: contract.schema_version,
    agent_id: contract.agent_id,
    layer: contract.layer,
    cohort: contract.cohort,
    prompt_version: contract.prompt_version,
    role_contract: {
      responsibility: contract.role_contract.responsibility,
      may_decide: [...contract.role_contract.may_decide].sort(),
      must_not_decide: [...contract.role_contract.must_not_decide].sort(),
    },
    required_tools: [...contract.required_tools]
      .sort((left, right) => left.name.localeCompare(right.name))
      .map((tool) => ({
        name: tool.name,
        freshness_max_days: tool.freshness_max_days,
        required: tool.required,
        metric_ids: [...tool.metric_ids].sort(),
        metric_candidate_ids: [...tool.metric_candidate_ids].sort(),
        analysis_recipe_ids: [...tool.analysis_recipe_ids].sort(),
        pit_required_for_backtest: tool.pit_required_for_backtest,
        fallback_confidence_cap: tool.fallback_confidence_cap,
        lineage: sortRecord(tool.lineage),
      })),
    fallback_tools: [...contract.fallback_tools].sort((left, right) =>
      left.name.localeCompare(right.name),
    ),
    research_rule_pack_refs: [...contract.research_rule_pack_refs].sort(),
    confidence_policy_ref: contract.confidence_policy_ref,
    rule_aggregation_policy_ref: contract.rule_aggregation_policy_ref,
    output_schema_ref: contract.output_schema_ref,
    output_schema_fields: [...contract.output_schema_fields].sort(),
    progress_event_schema_ref: contract.progress_event_schema_ref,
    handoff_schema_ref: contract.handoff_schema_ref,
    evolution_targets: {
      allowed_paths: [...contract.evolution_targets.allowed_paths].sort(),
      forbidden_paths: [...contract.evolution_targets.forbidden_paths].sort(),
    },
    guardrails: [...contract.guardrails].sort(),
    shared_contract_refs: [...contract.shared_contract_refs].sort(),
    status: contract.status,
  };
}

function sortRecord<T>(record: Record<string, T>): Record<string, T> {
  return Object.fromEntries(
    Object.entries(record).sort(([left], [right]) => left.localeCompare(right)),
  );
}
