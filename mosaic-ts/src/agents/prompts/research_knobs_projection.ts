import { type ResearchKnobs, renderResearchKnobsFence } from "../helpers/research_knobs.js";
import { domainKnobCardsForSpec } from "./domain_knob_catalog.js";
import {
  applyDomainKnobValueToProjection,
  type DomainKnobValueRegistry,
  domainKnobValueForCard,
} from "./domain_knob_registry.js";
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

export function buildRuntimeResearchKnobs(
  spec: RuntimeAgentSpec,
  opts: { domainRegistry?: DomainKnobValueRegistry | null } = {},
): ResearchKnobs {
  const rulePackId = `${spec.layer}.${spec.agent}.runtime.v1`;
  const ruleId = canonicalRuntimeRuleId(spec);
  const nonRkeTools = spec.requiredTools.filter((tool) => tool !== "get_rke_research_context");
  const evidenceRegistry: ResearchKnobs["evidence_registry"] = {};
  const evidenceWeights: ResearchKnobs["evidence_weights"] = {};
  const mutationTargets: ResearchKnobs["mutation_targets"] = [];
  const lookbacks: ResearchKnobs["lookbacks"] = {};
  const thresholds: ResearchKnobs["thresholds"] = {};
  const tieBreaks: ResearchKnobs["tie_breaks"] = [];

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

  if (spec.layer === "decision") {
    evidenceRegistry.current_position_snapshot = {
      source: "daily_cycle_state",
      metric: "current_position_snapshot",
      current_data: true,
      primary: true,
    };
    evidenceRegistry.current_market_data = {
      source: "daily_cycle_state",
      metric: "current_market_data",
      current_data: true,
      primary: true,
    };
    evidenceRegistry.mirofish_context = {
      source: "daily_cycle_state",
      metric: "mirofish_context",
      current_data: false,
      primary: false,
    };
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

  const requiredEvidence = Object.entries(evidenceRegistry)
    .filter(([, entry]) => entry.current_data && entry.primary && (entry.tool || entry.source))
    .map(([key]) => key);
  const confidenceCaps: ResearchKnobs["confidence_caps"] = {
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
  };

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

  const domainCards = domainKnobCardsForSpec(spec);
  for (const card of domainCards) {
    if (card.coverage_level === "gap_pending_tool") continue;
    applyDomainKnobValueToProjection(
      {
        evidence_weights: evidenceWeights,
        lookbacks,
        thresholds,
        confidence_caps: confidenceCaps,
        tie_breaks: tieBreaks,
      },
      card,
      domainKnobValueForCard(card, opts.domainRegistry),
    );
    mutationTargets.push({
      path: card.path,
      type: card.type,
      ...(card.min !== undefined ? { min: card.min } : {}),
      ...(card.max !== undefined ? { max: card.max } : {}),
      ...(card.step !== undefined ? { step: card.step } : {}),
      ...(card.allowed_values !== undefined ? { allowed_values: card.allowed_values } : {}),
    });
  }

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
      ...domainPredictionTargets(domainCards),
    ],
    evidence_registry: evidenceRegistry,
    evidence_weights: evidenceWeights,
    lookbacks,
    thresholds,
    confidence_caps: confidenceCaps,
    tie_breaks: tieBreaks,
    mutation_targets: mutationTargets,
    projection_metadata: {
      source: "runtime_agent_spec_projection",
      domain_knob_catalog: {
        authority: "domain_knob_catalog_v1",
        card_count: domainCards.length,
        domain_mutation_target_count: domainCards.filter(
          (card) => card.coverage_level !== "gap_pending_tool",
        ).length,
        cards: domainCards
          .filter((card) => card.coverage_level !== "gap_pending_tool")
          .map((card) => ({
            id: card.id,
            path: card.path,
            projection_bucket: card.projection_bucket,
            default: card.default,
            runtime_input_sources: card.runtime_input_sources,
            runtime_input_source_policies: card.runtime_input_source_policies,
            evidence_dependencies: card.evidence_dependencies,
            evidence_dependency_policies: card.evidence_dependency_policies,
            evaluation_metric: card.evaluation_metric,
            learning_objective: card.learning_objective,
            enforcement: card.enforcement,
            cross_field_group: card.cross_field_group,
            weight_group: card.weight_group,
            normalization: card.normalization,
            ...(card.runtime_validator ? { runtime_validator: card.runtime_validator } : {}),
            ...(card.audit_field ? { audit_field: card.audit_field } : {}),
          })),
        weight_groups: domainWeightGroupMetadata(domainCards),
        cross_field_groups: domainCrossFieldGroupMetadata(domainCards),
        runtime_sources: [
          ...new Set(domainCards.flatMap((card) => card.runtime_input_sources)),
        ].sort(),
        evaluation_metrics: [...new Set(domainCards.map((card) => card.evaluation_metric))].sort(),
      },
      prompt_ir_agent_id: spec.promptIrAgentId,
      rke_prior_shadow_only: true,
    },
  };
}

function domainWeightGroupMetadata(
  cards: ReturnType<typeof domainKnobCardsForSpec>,
): Record<string, unknown> {
  const groups = new Map<string, typeof cards>();
  for (const card of cards) {
    if (!card.weight_group) continue;
    const members = groups.get(card.weight_group) ?? [];
    members.push(card);
    groups.set(card.weight_group, members);
  }
  return Object.fromEntries(
    [...groups.entries()].map(([group, members]) => [
      group,
      {
        normalization: "sum_to_one",
        projection_bucket: members[0]?.projection_bucket ?? "thresholds",
        members: members.map((card) => card.id),
      },
    ]),
  );
}

function domainCrossFieldGroupMetadata(
  cards: ReturnType<typeof domainKnobCardsForSpec>,
): Record<string, unknown> {
  const groups = new Map<string, typeof cards>();
  for (const card of cards) {
    if (!card.cross_field_group) continue;
    const members = groups.get(card.cross_field_group) ?? [];
    members.push(card);
    groups.set(card.cross_field_group, members);
  }
  return Object.fromEntries(
    [...groups.entries()].map(([group, members]) => [
      group,
      { members: members.map((card) => card.id) },
    ]),
  );
}

function domainPredictionTargets(
  cards: ReturnType<typeof domainKnobCardsForSpec>,
): ResearchKnobs["prediction_targets"] {
  const seen = new Set<string>();
  const targets: ResearchKnobs["prediction_targets"] = [];
  for (const card of cards) {
    if (seen.has(card.prediction_target)) continue;
    seen.add(card.prediction_target);
    targets.push({
      id: card.prediction_target,
      target_variable: card.id,
      horizon: card.horizon,
      allowed_outputs: ["worse", "neutral", "better"],
    });
  }
  return targets;
}

function canonicalRuntimeRuleId(spec: RuntimeAgentSpec): string {
  const kind = spec.layer === "decision" ? (spec.agent === "cro" ? "risk" : "policy") : "soft";
  return `${spec.layer}.${spec.agent}.${kind}.001`;
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
