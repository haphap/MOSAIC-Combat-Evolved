import { type ResearchKnobs, renderResearchKnobsFence } from "../helpers/research_knobs.js";
import type { RuntimeAgentSpec } from "./runtime_agent_spec.js";

const FENCE_RE = /```research-knobs\s*\n[\s\S]*?```/g;

const HORIZON_BY_LAYER = {
  macro: "5d",
  sector: "20d",
  superinvestor: "60d",
  decision: "20d",
} as const;

const MUST_NOT_COVER_BY_LAYER = {
  macro: ["final_portfolio_sizing", "single_stock_recommendation"],
  sector: ["final_portfolio_sizing", "macro_regime_decision"],
  superinvestor: ["sector_coverage", "final_portfolio_sizing"],
  decision: ["source_data_extraction", "report_outcome_labeling"],
} as const;

export function buildRuntimeResearchKnobs(spec: RuntimeAgentSpec): ResearchKnobs {
  const rulePackId = `${spec.layer}.${spec.agent}.runtime.v1`;
  const ruleId = `${spec.layer}.${spec.agent}.primary.001`;
  const nonRkeTools = spec.requiredTools.filter((tool) => tool !== "get_rke_research_context");
  const evidenceRegistry: ResearchKnobs["evidence_registry"] = {};
  const evidenceWeights: ResearchKnobs["evidence_weights"] = {};
  const mutationTargets: ResearchKnobs["mutation_targets"] = [];

  const weightedKeys =
    nonRkeTools.length > 0
      ? nonRkeTools.map((tool) => evidenceKeyForTool(tool))
      : ["upstream_context"];
  const unitWeight = weightedKeys.length > 0 ? 1 / weightedKeys.length : 0;

  for (const tool of nonRkeTools) {
    const key = evidenceKeyForTool(tool);
    evidenceRegistry[key] = {
      tool,
      metric: metricForTool(tool),
      current_data: true,
      primary: key === weightedKeys[0],
      fallback_confidence_cap: 0.6,
    };
    evidenceWeights[key] = unitWeight;
    mutationTargets.push({
      path: `/rule_packs/${rulePackId}/rules/${ruleId}/learnable_parameters/${key}_weight/value`,
      type: "number",
      min: 0,
      max: 1,
      step: 0.05,
    });
  }

  if (nonRkeTools.length === 0) {
    evidenceRegistry.upstream_context = {
      source: "daily_cycle_state",
      metric: "upstream_agent_outputs",
      current_data: true,
      primary: true,
    };
    evidenceWeights.upstream_context = 1;
    mutationTargets.push({
      path: `/rule_packs/${rulePackId}/rules/${ruleId}/learnable_parameters/upstream_context_weight/value`,
      type: "number",
      min: 0,
      max: 1,
      step: 0.05,
    });
  }

  if (spec.requiredTools.includes("get_rke_research_context")) {
    evidenceRegistry.rke_prior = {
      tool: "get_rke_research_context",
      metric: "research_prior",
      current_data: false,
      primary: false,
    };
    evidenceWeights.rke_prior = 0;
  }

  mutationTargets.push({
    path: `/rule_packs/${rulePackId}/rules/${ruleId}/confidence_policy/missing_current_data/cap`,
    type: "number",
    min: 0.25,
    max: 0.75,
    step: 0.05,
  });
  mutationTargets.push({
    path: `/rule_packs/${rulePackId}/rules/${ruleId}/confidence_policy/fallback_primary_tool/cap`,
    type: "number",
    min: 0.25,
    max: 0.75,
    step: 0.05,
  });

  const requiredEvidence = Object.entries(evidenceRegistry)
    .filter(([, entry]) => entry.current_data && entry.primary && entry.tool)
    .map(([key]) => key);

  return {
    schema_version: "research_knobs_v1",
    layer: spec.layer,
    agent: spec.promptIrAgentId,
    research_scope: {
      must_cover: spec.fieldNames.filter((field) => field !== "confidence"),
      must_not_cover: [...MUST_NOT_COVER_BY_LAYER[spec.layer]],
    },
    prediction_targets: [
      {
        id: ruleId,
        target_variable: primaryTargetVariable(spec),
        horizon: HORIZON_BY_LAYER[spec.layer],
        allowed_outputs: ["negative", "neutral", "positive"],
      },
    ],
    evidence_registry: evidenceRegistry,
    evidence_weights: evidenceWeights,
    lookbacks: {},
    thresholds: {},
    confidence_caps: {
      missing_current_data: {
        cap: 0.55,
        trigger: "missing_required_evidence",
        enforcement: "code",
        required_evidence: requiredEvidence,
      },
      fallback_primary_tool: {
        cap: 0.6,
        trigger: "primary_tool_failed_or_fallback",
        enforcement: "code",
        required_evidence: requiredEvidence,
      },
    },
    tie_breaks: [],
    mutation_targets: mutationTargets,
    projection_metadata: {
      source: "runtime_agent_spec_projection",
      prompt_ir_agent_id: spec.promptIrAgentId,
      rke_prior_shadow_only: true,
    },
  };
}

export function upsertResearchKnobsFence(text: string, knobs: ResearchKnobs): string {
  const fence = renderResearchKnobsFence(knobs);
  const matches = [...text.matchAll(FENCE_RE)];
  if (matches.length > 1) {
    throw new Error(`expected at most one research-knobs fence, found ${matches.length}`);
  }
  if (matches.length === 1) {
    return `${text.replace(matches[0]?.[0] ?? "", fence).trimEnd()}\n`;
  }
  const marker = findInsertionMarker(text);
  if (!marker) return `${fence}\n\n${text.trimStart()}`;
  return text.replace(marker, `${fence}\n\n${marker}`);
}

function evidenceKeyForTool(tool: string): string {
  return tool
    .replace(/^get_/, "")
    .replace(/[^a-zA-Z0-9]+/g, "_")
    .replace(/_+$/g, "");
}

function metricForTool(tool: string): string {
  return `${evidenceKeyForTool(tool)}_current`;
}

function primaryTargetVariable(spec: RuntimeAgentSpec): string {
  return (
    spec.fieldNames.find((field) => !["key_drivers", "confidence"].includes(field)) ??
    "agent_signal"
  );
}

function findInsertionMarker(text: string): string | null {
  const markers = [
    "## Mutable Research Knobs",
    "## 可变研究旋钮",
    "## Output Schema",
    "## 输出 schema",
  ];
  return markers.find((marker) => text.includes(marker)) ?? null;
}
