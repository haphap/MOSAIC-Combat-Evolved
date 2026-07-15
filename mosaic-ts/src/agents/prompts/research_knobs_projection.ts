import { type ResearchKnobs, renderResearchKnobsFence } from "../helpers/research_knobs.js";
import { domainKnobCardsForSpec } from "./domain_knob_catalog.js";
import {
  applyDomainKnobValueToProjection,
  type DomainKnobValueRegistry,
  domainKnobValueForCard,
} from "./domain_knob_registry.js";
import {
  evidenceKeyForTool,
  genericGovernanceTargetDefinitions,
  type PromptGovernanceValueRegistry,
  promptGovernanceValueForDefinition,
} from "./prompt_governance_registry.js";
import type { RuntimeAgentSpec } from "./runtime_agent_spec.js";

const FENCE_RE = /```research-knobs\s*\n[\s\S]*?```/g;
const EVIDENCE_CONTRACT_RE =
  /<!-- runtime-evidence-contract:start -->[\s\S]*?<!-- runtime-evidence-contract:end -->/g;

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
  opts: {
    domainRegistry?: DomainKnobValueRegistry | null;
    governanceRegistry?: PromptGovernanceValueRegistry | null;
  } = {},
): ResearchKnobs {
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
  const genericDefinitions = genericGovernanceTargetDefinitions(spec);
  const genericByEvidenceKey = new Map(
    genericDefinitions.flatMap((definition) =>
      definition.evidenceKey ? [[definition.evidenceKey, definition] as const] : [],
    ),
  );
  const genericByConfidenceCap = new Map(
    genericDefinitions.flatMap((definition) =>
      definition.confidenceCapId ? [[definition.confidenceCapId, definition] as const] : [],
    ),
  );

  for (const tool of nonRkeTools) {
    const key = evidenceKeyForTool(tool);
    evidenceRegistry[key] = {
      tool,
      metric: metricForTool(tool),
      current_data: true,
      primary: key === weightedKeys[0],
      fallback_confidence_cap: 0.6,
    };
    const definition = genericByEvidenceKey.get(key);
    if (!definition) throw new Error(`${spec.agent}: missing governance target for ${key}`);
    evidenceWeights[key] = promptGovernanceValueForDefinition(definition, opts.governanceRegistry);
  }

  if (nonRkeTools.length === 0) {
    evidenceRegistry.upstream_context = {
      source: "daily_cycle_state",
      metric: "upstream_agent_outputs",
      current_data: true,
      primary: true,
    };
    const definition = genericByEvidenceKey.get("upstream_context");
    if (!definition) throw new Error(`${spec.agent}: missing upstream governance target`);
    evidenceWeights.upstream_context = promptGovernanceValueForDefinition(
      definition,
      opts.governanceRegistry,
    );
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
      cap: governanceConfidenceCap(
        "missing_current_data",
        genericByConfidenceCap,
        opts.governanceRegistry,
      ),
      trigger: "missing_required_evidence",
      enforcement: "code",
      required_evidence: requiredEvidence,
    },
    fallback_primary_tool: {
      cap: governanceConfidenceCap(
        "fallback_primary_tool",
        genericByConfidenceCap,
        opts.governanceRegistry,
      ),
      trigger: "primary_tool_failed_or_fallback",
      enforcement: "code",
      required_evidence: requiredEvidence,
    },
  };

  mutationTargets.push(...genericDefinitions.map((definition) => definition.target));

  const domainCards = domainKnobCardsForSpec(spec);
  for (const card of domainCards) {
    if (card.coverage_level === "gap_pending_tool" || card.activation_state === "backlog") {
      continue;
    }
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
    if (card.activation_state !== "active") continue;
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
      ...domainPredictionTargets(
        domainCards.filter(
          (card) =>
            card.coverage_level !== "gap_pending_tool" && card.activation_state !== "backlog",
        ),
      ),
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
          (card) =>
            card.coverage_level !== "gap_pending_tool" && card.activation_state === "active",
        ).length,
        cards: domainCards
          .filter((card) => card.coverage_level !== "gap_pending_tool")
          .map((card) => ({
            id: card.id,
            path: card.path,
            projection_bucket: card.projection_bucket,
            default: card.default,
            owner_stage: card.owner_stage,
            consumer_stages: card.consumer_stages,
            runtime_input_sources: card.runtime_input_sources,
            runtime_input_source_policies: card.runtime_input_source_policies,
            evidence_dependencies: card.evidence_dependencies.map((dependency) => ({
              dependency_id: dependency.dependency_id,
              evidence_key: dependency.evidence_key,
              tool: dependency.tool,
              metric_ids: dependency.metric_ids,
              scope_resolution: dependency.scope_resolution,
              ...(dependency.scope_source_tool
                ? { scope_source_tool: dependency.scope_source_tool }
                : {}),
              ...(dependency.max_scope_count !== undefined
                ? { max_scope_count: dependency.max_scope_count }
                : {}),
              ...(dependency.min_scope_count !== undefined
                ? { min_scope_count: dependency.min_scope_count }
                : {}),
              ...(dependency.empty_scope_behavior
                ? { empty_scope_behavior: dependency.empty_scope_behavior }
                : {}),
              ...(dependency.min_scope_coverage !== undefined
                ? { min_scope_coverage: dependency.min_scope_coverage }
                : {}),
            })),
            evidence_dependency_policies: card.evidence_dependency_policies,
          })),
      },
      prompt_ir_agent_id: spec.promptIrAgentId,
      rke_prior_shadow_only: true,
    },
  };
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

export function upsertRuntimeEvidenceContract(
  text: string,
  spec: RuntimeAgentSpec,
  language: "zh" | "en",
  opts: { includeResearchKnobDetails?: boolean } = {},
): string {
  if (!spec.fieldNames.includes("claims")) return text;
  const outputFields = spec.fieldNames.map((field) => `\`${field}\``).join(", ");
  const domainCards = domainKnobCardsForSpec(spec);
  const domainCardIds = domainCards.map((card) => `\`${card.id}\``).join(", ");
  const requiredTools = spec.requiredTools.map((tool) => `\`${tool}\``).join(", ");
  const influenceFields = domainCards.some((card) => card.evidence_dependencies.length > 0)
    ? "`declared_knob_influence_ids`, `declared_influence_rationale`"
    : "(none)";
  let body: string[];
  if (spec.layer === "macro" && language === "zh") {
    body = [
      "## 运行时证据输出合同",
      "运行时提供本次调用唯一有效的证据目录与研究规则 ID。",
      `输出字段包括：${outputFields}。`,
      `必需运行时工具：${requiredTools || "（无）"}。`,
      ...(opts.includeResearchKnobDetails === false
        ? []
        : [
            `本角色的领域旋钮卡片 ID：${domainCardIds || "（无）"}。`,
            `旋钮影响审计字段：${influenceFields}。`,
          ]),
      "必须输出 `claims` 与 `claim_refs`。每个非 `uncertainty` claim 必须通过 " +
        "`evidence_refs` 引用证据目录中的 `evidence_id`；每个 `inference` claim 还必须通过 " +
        "`research_rule_refs` 引用允许的规则 ID。所有建议、候选、标的选择、仓位决策、组合操作、" +
        "风险调整或执行检查都必须用 `claim_refs` 引用支持它的 claim。" +
        "必需证据不足时拒绝本阶段，不得生成宏观输出；只有证据有效但相互冲突时，才能输出带证据引用的 " +
        "`uncertainty` 声明。不得伪造证据 ID、指纹、规则 ID 或跨运行引用。",
    ];
  } else if (spec.layer === "macro") {
    body = [
      "## Runtime Evidence Output Contract",
      "Runtime supplies the only valid evidence catalog and research rule ids for this invocation.",
      `Output fields include: ${outputFields}.`,
      `Required runtime tools: ${requiredTools || "(none)"}.`,
      ...(opts.includeResearchKnobDetails === false
        ? []
        : [
            `Domain knob card ids for this agent: ${domainCardIds || "(none)"}.`,
            `Knob influence audit fields: ${influenceFields}.`,
          ]),
      "Emit `claims` and `claim_refs`. Every non-uncertainty claim must cite catalog " +
        "`evidence_id` values through `evidence_refs`; every inference claim must also cite an " +
        "allowed rule through `research_rule_refs`. Every recommendation, candidate, pick, " +
        "position decision, portfolio action, risk adjustment, or execution check must use " +
        "`claim_refs` to cite its supporting claim. When required evidence is insufficient, reject the stage " +
        "without emitting a Macro output. Only valid but conflicting evidence may produce an evidence-backed " +
        "`uncertainty` claim. Never invent evidence ids, fingerprints, " +
        "rule ids, or cross-run references.",
    ];
  } else if (language === "zh") {
    // Preserve the established non-Macro projection byte-for-byte. This command
    // rebuilds Macro prompts only and must not create unrelated private drift.
    body = [
      "## Runtime Evidence Output Contract",
      "Runtime 提供本次调用唯一有效的 evidence catalog 与 research rule ids。",
      `输出字段包括：${outputFields}。`,
      `必需 runtime tools：${requiredTools || "(none)"}。`,
      ...(opts.includeResearchKnobDetails === false
        ? []
        : [
            `本 agent 的 domain knob card ids：${domainCardIds || "(none)"}。`,
            `Knob influence 审计字段：${influenceFields}。`,
          ]),
      "必须输出 `claims` 与 `claim_refs`。每个非 uncertainty claim 必须通过 " +
        "`evidence_refs` 引用 catalog 中的 `evidence_id`；每个 inference claim 还必须通过 " +
        "`research_rule_refs` 引用允许的 rule id。所有 recommendation、candidate、pick、" +
        "position decision、portfolio action、risk adjustment 或 execution check 都必须用 " +
        "`claim_refs` 引用支持它的 claim。证据不足时输出有证据支持的显式空 disposition 与 uncertainty " +
        "claim，不得伪造 evidence id、fingerprint、rule id 或跨 run 引用。",
    ];
  } else {
    body = [
      "## Runtime Evidence Output Contract",
      "Runtime supplies the only valid evidence catalog and research rule ids for this invocation.",
      `Output fields include: ${outputFields}.`,
      `Required runtime tools: ${requiredTools || "(none)"}.`,
      ...(opts.includeResearchKnobDetails === false
        ? []
        : [
            `Domain knob card ids for this agent: ${domainCardIds || "(none)"}.`,
            `Knob influence audit fields: ${influenceFields}.`,
          ]),
      "Emit `claims` and `claim_refs`. Every non-uncertainty claim must cite catalog " +
        "`evidence_id` values through `evidence_refs`; every inference claim must also cite an " +
        "allowed rule through `research_rule_refs`. Every recommendation, candidate, pick, " +
        "position decision, portfolio action, risk adjustment, or execution check must use " +
        "`claim_refs` to cite its supporting claim. When evidence is insufficient, emit an " +
        "evidence-backed explicit empty disposition and an uncertainty claim; never invent evidence ids, fingerprints, " +
        "rule ids, or cross-run references.",
    ];
  }
  const block = [
    "<!-- runtime-evidence-contract:start -->",
    ...body,
    "<!-- runtime-evidence-contract:end -->",
  ].join("\n\n");
  const cleaned = text.replace(EVIDENCE_CONTRACT_RE, "").trimEnd();
  return `${cleaned}\n\n${block}\n`;
}

function metricForTool(tool: string): string {
  return `${evidenceKeyForTool(tool)}_current`;
}

function governanceConfidenceCap(
  capId: string,
  definitions: ReadonlyMap<string, ReturnType<typeof genericGovernanceTargetDefinitions>[number]>,
  registry?: PromptGovernanceValueRegistry | null,
): number {
  const definition = definitions.get(capId);
  if (!definition) throw new Error(`missing governance target for confidence cap ${capId}`);
  return promptGovernanceValueForDefinition(definition, registry);
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
