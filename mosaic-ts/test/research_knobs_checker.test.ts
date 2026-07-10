import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { ResearchKnobs } from "../src/agents/helpers/research_knobs.js";
import { AGENTS_BY_LAYER } from "../src/agents/prompts/cohorts.js";
import {
  buildDomainKnobCatalogArtifact,
  buildDomainKnobEvaluationContractArtifact,
  DOMAIN_KNOB_CATALOG_VERSION,
  type DomainKnobCard,
  domainKnobCardsForSpec,
  EVALUATION_CALCULATOR_REGISTRY,
  EVALUATION_METRIC_REGISTRY,
  minDomainTargetCount,
  PROJECTION_BUCKETS,
  RUNTIME_SOURCE_REGISTRY,
  validateDomainKnobCatalogArtifact,
  validateDomainKnobEvaluationContractArtifact,
} from "../src/agents/prompts/domain_knob_catalog.js";
import {
  buildDomainKnobValueRegistry,
  domainKnobValueRegistryPath,
} from "../src/agents/prompts/domain_knob_registry.js";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import {
  buildPromptIrContract,
  promptIrPathForSpec,
  renderPromptIrContract,
} from "../src/agents/prompts/prompt_ir_registry.js";
import { checkResearchKnobsPrompts } from "../src/agents/prompts/research_knobs_checker.js";
import {
  buildRuntimeResearchKnobs,
  upsertResearchKnobsFence,
} from "../src/agents/prompts/research_knobs_projection.js";
import {
  RUNTIME_AGENT_SPECS,
  type RuntimeAgentSpec,
} from "../src/agents/prompts/runtime_agent_spec.js";

interface FakeRoot {
  root: string;
  cleanup: () => void;
}

function makeRoot(): FakeRoot {
  const root = mkdtempSync(join(tmpdir(), "mosaic-knobs-check-"));
  return { root, cleanup: () => rmSync(root, { recursive: true, force: true }) };
}

function writePrompt(
  root: string,
  agent: string,
  layer: string,
  lang: "zh" | "en",
  text: string,
): void {
  const dir = join(root, "cohort_default", layer);
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, `${agent}.${lang}.md`), text, "utf-8");
}

function researchKnobsFence(): string {
  return `\`\`\`research-knobs
research-knobs:
  schema_version: research_knobs_v1
  layer: macro
  agent: macro.central_bank
  research_scope:
    must_cover: [liquidity_regime]
    must_not_cover: [final_portfolio_sizing]
  prediction_targets:
    - id: policy_stance_1w
      target_variable: central_bank_stance
      horizon: 1w
      allowed_outputs: [tightening, neutral, easing]
  evidence_registry:
    pboc_liquidity:
      tool: get_pboc_ops
      metric: pboc_net_injection_7d
      current_data: true
      primary: true
  evidence_weights:
    pboc_liquidity: 1.0
  lookbacks:
    net_injection_window_days: 7
  thresholds: {}
  confidence_caps:
    missing_current_data:
      cap: 0.55
      trigger: missing_required_evidence
      enforcement: code
      required_evidence: [pboc_liquidity]
  tie_breaks: []
  mutation_targets:
    - path: /rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/pboc_liquidity_weight/value
      type: number
      min: 0
      max: 1
\`\`\``;
}

function generatedFence(agent = "central_bank"): string {
  const spec = specForAgent(agent);
  return upsertResearchKnobsFence("", buildRuntimeResearchKnobs(spec)).trim();
}

function specForAgent(agent: string): RuntimeAgentSpec {
  const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === agent);
  if (!spec) throw new Error(`missing spec for ${agent}`);
  return spec;
}

function promptBodyForSpec(spec: RuntimeAgentSpec, lang: "zh" | "en"): string {
  return [
    `# ${spec.agent} ${lang}`,
    "",
    "## Required Inputs and Tools",
    ...spec.requiredTools.map((tool) => `- ${tool}`),
    "",
    "## Output Schema",
    ...spec.fieldNames.map((field) => `- ${field}`),
    "- declared_knob_influence_ids",
    "- declared_influence_rationale",
  ].join("\n");
}

describe("checkResearchKnobsPrompts", () => {
  let fake: FakeRoot;
  beforeEach(() => {
    fake = makeRoot();
    clearPromptCache();
  });

  afterEach(() => {
    fake.cleanup();
    clearPromptCache();
  });

  it("checks enabled runtime agents and reports legacy agents explicitly", async () => {
    writePrompt(
      fake.root,
      "central_bank",
      "macro",
      "zh",
      `${generatedFence()}\n\n${promptBodyForSpec(specForAgent("central_bank"), "zh")}`,
    );
    writePrompt(
      fake.root,
      "central_bank",
      "macro",
      "en",
      `${generatedFence()}\n\n${promptBodyForSpec(specForAgent("central_bank"), "en")}`,
    );

    const report = await checkResearchKnobsPrompts({
      cohort: "cohort_default",
      promptsRoot: fake.root,
      enabledAgents: new Set(["central_bank"]),
    });

    expect(report.ready).toBe(true);
    expect(report.total_runtime_agents).toBe(25);
    expect(report.total_runtime_stages).toBe(26);
    expect(report.enabled_agents).toEqual(["central_bank"]);
    expect(report.enabled_agent_stages).toEqual(["central_bank:agent_run"]);
    expect(report.legacy_agents).toHaveLength(24);
    expect(report.legacy_agent_stages).toHaveLength(25);
    const row = report.rows.find((item) => item.agent === "central_bank");
    expect(row?.status).toBe("ready");
    expect(row?.snapshot_hash).toMatch(/^sha256:/);
    for (const agent of AGENTS_BY_LAYER.sector) {
      expect(report.legacy_agents).toContain(agent);
    }
  });

  it("fails enabled agents without a research-knobs fence", async () => {
    writePrompt(fake.root, "central_bank", "macro", "zh", "# central_bank zh");
    writePrompt(fake.root, "central_bank", "macro", "en", "# central_bank en");

    const report = await checkResearchKnobsPrompts({
      cohort: "cohort_default",
      promptsRoot: fake.root,
      enabledAgents: new Set(["central_bank"]),
    });

    expect(report.ready).toBe(false);
    const row = report.rows.find((item) => item.agent === "central_bank");
    expect(row?.status).toBe("failed");
    expect(row?.reasons.join("\n")).toContain("expected exactly one research-knobs fence");
  });

  it("supports an explicit per-stage enablement gate for multi-stage CIO", async () => {
    const spec = specForAgent("cio");
    const knobs = buildRuntimeResearchKnobs(spec);
    for (const lang of ["zh", "en"] as const) {
      writePrompt(
        fake.root,
        spec.agent,
        spec.layer,
        lang,
        upsertResearchKnobsFence(promptBodyForSpec(spec, lang), knobs),
      );
    }

    const report = await checkResearchKnobsPrompts({
      cohort: "cohort_default",
      promptsRoot: fake.root,
      enabledAgentStages: new Set(["cio:cio_proposal"]),
    });

    expect(report.ready).toBe(true);
    expect(report.enabled_agents).toEqual(["cio"]);
    expect(report.enabled_agent_stages).toEqual(["cio:cio_proposal"]);
    expect(report.legacy_agent_stages).toContain("cio:cio_final");
    expect(
      report.rows.find((row) => row.agent === "cio" && row.stage === "cio_proposal")?.status,
    ).toBe("ready");
  });

  it("fails when prompt prose omits a required runtime tool", async () => {
    const spec = specForAgent("semiconductor");
    const knobs = buildRuntimeResearchKnobs(spec);
    for (const lang of ["zh", "en"] as const) {
      writePrompt(
        fake.root,
        spec.agent,
        spec.layer,
        lang,
        upsertResearchKnobsFence(
          promptBodyForSpec(spec, lang).replace("- get_cashflow\n", ""),
          knobs,
        ),
      );
    }

    const report = await checkResearchKnobsPrompts({
      cohort: "cohort_default",
      promptsRoot: fake.root,
      enabledAgents: new Set(["semiconductor"]),
    });

    expect(report.ready).toBe(false);
    expect(report.rows.find((item) => item.agent === "semiconductor")?.reasons).toContain(
      "required_tool_missing_from_prompt_body:get_cashflow",
    );
  });

  it("fails when evidence metrics are not registered for the tool", async () => {
    const spec = specForAgent("central_bank");
    const knobs = buildRuntimeResearchKnobs(spec);
    const pboc = knobs.evidence_registry.pboc_ops;
    expect(pboc).toBeDefined();
    if (!pboc) return;
    pboc.metric = "unregistered_pboc_metric";
    for (const lang of ["zh", "en"] as const) {
      writePrompt(
        fake.root,
        spec.agent,
        spec.layer,
        lang,
        upsertResearchKnobsFence(promptBodyForSpec(spec, lang), knobs),
      );
    }

    const report = await checkResearchKnobsPrompts({
      cohort: "cohort_default",
      promptsRoot: fake.root,
      enabledAgents: new Set(["central_bank"]),
    });

    expect(report.ready).toBe(false);
    expect(report.rows.find((item) => item.agent === "central_bank")?.reasons).toContain(
      "evidence_metric_not_registered:pboc_ops:unregistered_pboc_metric",
    );
  });

  it("fails when prompt prose omits knob influence declaration fields", async () => {
    const spec = specForAgent("central_bank");
    const knobs = buildRuntimeResearchKnobs(spec);
    for (const lang of ["zh", "en"] as const) {
      writePrompt(
        fake.root,
        spec.agent,
        spec.layer,
        lang,
        upsertResearchKnobsFence(
          promptBodyForSpec(spec, lang).replace("- declared_knob_influence_ids\n", ""),
          knobs,
        ),
      );
    }

    const report = await checkResearchKnobsPrompts({
      cohort: "cohort_default",
      promptsRoot: fake.root,
      enabledAgents: new Set(["central_bank"]),
    });

    expect(report.ready).toBe(false);
    expect(report.rows.find((item) => item.agent === "central_bank")?.reasons).toContain(
      "knob_influence_field_missing_from_prompt_body:declared_knob_influence_ids",
    );
  });

  it("fails stale projections that no longer match generated runtime knobs", async () => {
    const spec = specForAgent("central_bank");
    const knobs = buildRuntimeResearchKnobs(spec);
    knobs.lookbacks.unregistered_runtime_window_days = 13;
    for (const lang of ["zh", "en"] as const) {
      writePrompt(
        fake.root,
        spec.agent,
        spec.layer,
        lang,
        upsertResearchKnobsFence(promptBodyForSpec(spec, lang), knobs),
      );
    }

    const report = await checkResearchKnobsPrompts({
      cohort: "cohort_default",
      promptsRoot: fake.root,
      enabledAgents: new Set(["central_bank"]),
    });

    expect(report.ready).toBe(false);
    expect(report.rows.find((item) => item.agent === "central_bank")?.reasons).toContain(
      "research_knobs_projection_stale_or_not_canonical",
    );
  });

  it("fails non-runtime prompt files in runtime layer directories", async () => {
    writePrompt(
      fake.root,
      "central_bank",
      "macro",
      "zh",
      `${generatedFence()}\n\n${promptBodyForSpec(specForAgent("central_bank"), "zh")}`,
    );
    writePrompt(
      fake.root,
      "central_bank",
      "macro",
      "en",
      `${generatedFence()}\n\n${promptBodyForSpec(specForAgent("central_bank"), "en")}`,
    );
    writePrompt(fake.root, "aschenbrenner", "superinvestor", "zh", "# orphan");

    const report = await checkResearchKnobsPrompts({
      cohort: "cohort_default",
      promptsRoot: fake.root,
      enabledAgents: new Set(["central_bank"]),
    });

    expect(report.ready).toBe(false);
    const row = report.rows.find((item) => item.agent === "aschenbrenner");
    expect(row?.status).toBe("failed");
    expect(row?.reasons.join("\n")).toContain("orphan_prompt_file");
  });

  it("accepts generated research-knobs projections for all 25 runtime agents", async () => {
    for (const spec of RUNTIME_AGENT_SPECS) {
      const knobs = buildRuntimeResearchKnobs(spec);
      for (const lang of ["zh", "en"] as const) {
        writePrompt(
          fake.root,
          spec.agent,
          spec.layer,
          lang,
          upsertResearchKnobsFence(promptBodyForSpec(spec, lang), knobs),
        );
      }
    }

    const report = await checkResearchKnobsPrompts({
      cohort: "cohort_default",
      promptsRoot: fake.root,
      enabledAgents: new Set(["*"]),
    });

    expect(report.ready).toBe(true);
    expect(report.enabled_agents).toHaveLength(25);
    expect(report.enabled_agent_stages).toHaveLength(26);
    expect(report.legacy_agents).toEqual([]);
    expect(report.legacy_agent_stages).toEqual([]);
    const cioSpec = RUNTIME_AGENT_SPECS.find((spec) => spec.agent === "cio");
    expect(cioSpec).toBeDefined();
    if (!cioSpec) return;
    const cioKnobs = buildRuntimeResearchKnobs(cioSpec);
    expect(cioKnobs.evidence_registry.upstream_context?.source).toBe("daily_cycle_state");
    expect(cioKnobs.evidence_weights.rke_prior).toBe(0);
    expect(cioKnobs.prediction_targets[0]?.id).toBe("decision.cio.policy.001");
    expect(cioKnobs.mutation_targets.map((target) => target.path).join("\n")).not.toContain(
      ".primary.001",
    );
    expect(
      domainKnobCardsForSpec(cioSpec)
        .filter((card) => card.activation_state === "active")
        .map((card) => card.id),
    ).toEqual([
      "stale_thesis_days",
      "rebalance_drift_pct",
      "min_confidence_to_add",
      "min_confidence_to_hold",
      "mirofish_portfolio_stress_weight",
      "mirofish_exit_regret_penalty",
      "mirofish_min_scenario_agreement_to_add",
      "mirofish_override_hurdle",
    ]);
    const croSpec = RUNTIME_AGENT_SPECS.find((spec) => spec.agent === "cro");
    const execSpec = RUNTIME_AGENT_SPECS.find((spec) => spec.agent === "autonomous_execution");
    expect(croSpec).toBeDefined();
    expect(execSpec).toBeDefined();
    if (!croSpec || !execSpec) return;
    expect(
      domainKnobCardsForSpec(croSpec)
        .filter((card) => card.activation_state === "active")
        .map((card) => card.id),
    ).toEqual([
      "stop_loss_pct",
      "take_profit_review_pct",
      "max_single_name_weight",
      "max_sector_weight",
      "mirofish_tail_scenario_weight",
      "mirofish_drawdown_penalty",
      "mirofish_max_tail_loss_to_hold",
      "mirofish_tail_risk_veto_threshold",
    ]);
    expect(
      domainKnobCardsForSpec(execSpec)
        .filter((card) => card.activation_state === "active")
        .map((card) => card.id),
    ).toEqual([
      "min_delta_trade_weight",
      "slippage_cap",
      "liquidity_floor",
      "max_order_split_count",
      "mirofish_path_sizing_weight",
      "mirofish_max_size_adjustment",
      "mirofish_turnover_penalty",
      "mirofish_liquidity_stress_haircut",
    ]);
    const semiconductorSpec = RUNTIME_AGENT_SPECS.find((spec) => spec.agent === "semiconductor");
    expect(semiconductorSpec).toBeDefined();
    if (!semiconductorSpec) return;
    const semiconductorKnobs = buildRuntimeResearchKnobs(semiconductorSpec);
    for (const id of [
      "financial_statement_quarters",
      "inventory_cycle_quarters",
      "capex_cycle_quarters",
    ]) {
      expect(semiconductorKnobs.lookbacks[id]).toBeDefined();
      expect(semiconductorKnobs.thresholds[id]).toBeUndefined();
    }
    for (const spec of RUNTIME_AGENT_SPECS) {
      const generated = buildRuntimeResearchKnobs(spec);
      const cards = domainKnobCardsForSpec(spec);
      expect(cards.length).toBeGreaterThanOrEqual(minDomainTargetCount(spec.layer, spec.agent));
      for (const card of cards) {
        expect(generated.mutation_targets.some((target) => target.path === card.path)).toBe(
          card.activation_state === "active",
        );
        expect(domainProjectionValue(generated, card)).toBe(card.default);
      }
    }
  });

  it("builds a complete machine-readable domain knob catalog artifact", () => {
    const artifact = buildDomainKnobCatalogArtifact();
    const cards = artifact.agents.flatMap((agent) => agent.cards);
    const cardPaths = cards.map((card) => card.path);

    expect(validateDomainKnobCatalogArtifact(artifact)).toEqual([]);
    expect(artifact.schema_version).toBe(DOMAIN_KNOB_CATALOG_VERSION);
    expect(artifact.runtime_agent_count).toBe(25);
    expect(artifact.agents).toHaveLength(25);
    expect(Object.keys(artifact.runtime_sources)).toEqual(
      Object.keys(RUNTIME_SOURCE_REGISTRY).sort(),
    );
    expect(Object.keys(artifact.evaluation_metrics)).toEqual(
      Object.keys(EVALUATION_METRIC_REGISTRY).sort(),
    );
    expect(Object.keys(artifact.evaluation_calculators)).toEqual(
      Object.keys(EVALUATION_CALCULATOR_REGISTRY).sort(),
    );
    for (const metric of Object.values(artifact.evaluation_metrics)) {
      expect(artifact.evaluation_calculators[metric.calculator_id]?.version).toBe(
        metric.calculator_version,
      );
      expect(metric.valid_range).toBeDefined();
      expect(metric.non_finite_policy).toBe("reject_evaluation");
      if (metric.direction === "lower_is_better") {
        expect(metric.value_convention).not.toBe("signed_return");
      }
      if (metric.direction === "higher_is_better") {
        expect(metric.value_convention).not.toBe("nonnegative_loss_magnitude");
        expect(metric.value_convention).not.toBe("bps_cost");
      }
    }
    expect(artifact.evaluation_metrics.macro_signal_accuracy_5d?.value_convention).toBe("rate_0_1");
    expect(artifact.evaluation_metrics.macro_signal_accuracy_5d?.aggregation).toBe("hit_rate");
    expect(artifact.evaluation_metrics.sector_rank_correlation_20d?.aggregation).toBe(
      "rank_correlation",
    );
    expect(artifact.evaluation_metrics.realized_slippage_bps?.aggregation).toBe("mean");
    expect(artifact.evaluation_metrics.max_drawdown_after_hold?.aggregation).toBe("max");
    expect(PROJECTION_BUCKETS).toEqual([
      "lookbacks",
      "thresholds",
      "tie_breaks",
      "evidence_weights",
      "confidence_caps",
    ]);
    const schema = JSON.parse(
      readFileSync(
        new URL("../../schemas/domain_knob_catalog_v1.schema.json", import.meta.url),
        "utf-8",
      ),
    ) as {
      properties: {
        agents: {
          items: {
            properties: { cards: { items: { properties: { projection_bucket: unknown } } } };
          };
        };
      };
    };
    expect(
      schema.properties.agents.items.properties.cards.items.properties.projection_bucket,
    ).toEqual({ enum: [...PROJECTION_BUCKETS] });
    expect(new Set(cardPaths).size).toBe(cardPaths.length);
    expect(cards.length).toBeGreaterThan(168);
    for (const agent of artifact.agents) {
      expect(agent.card_count).toBe(agent.cards.length);
      expect(agent.cards.length).toBeGreaterThanOrEqual(agent.min_mutable_domain_knobs);
    }
    for (const card of cards) {
      expect(card.category).toBe("domain");
      expect(["active", "read_only", "backlog"]).toContain(card.activation_state);
      expect(card.owner_agent).toContain(".");
      expect(card.path).toMatch(/^\/rule_packs\/[^/]+\/rules\/[^/]+\/learnable_parameters\//);
      expect(artifact.evaluation_metrics[card.evaluation_metric]).toBeDefined();
      expect(artifact.evaluation_metrics[card.rollback_condition.metric]).toBeDefined();
      for (const metricId of card.secondary_metrics) {
        expect(artifact.evaluation_metrics[metricId]).toBeDefined();
      }
      for (const source of card.runtime_input_sources) {
        expect(artifact.runtime_sources[source]).toBeDefined();
      }
    }
    const referencedMetricIds = new Set(
      cards.flatMap((card) => [
        card.evaluation_metric,
        card.rollback_condition.metric,
        ...card.secondary_metrics,
      ]),
    );
    expect([...referencedMetricIds].sort()).toEqual(
      [...referencedMetricIds].filter((id) => EVALUATION_METRIC_REGISTRY[id]).sort(),
    );
    const cioCards = artifact.agents.find((agent) => agent.agent === "cio")?.cards ?? [];
    expect(cioCards.map((card) => card.id)).toEqual(
      expect.arrayContaining([
        "target_count_min",
        "target_count_max",
        "max_target_position_weight",
        "new_buy_hurdle",
        "trim_threshold",
        "exit_threshold",
        "macro_signal_weight",
        "sector_signal_weight",
        "superinvestor_signal_weight",
        "cro_risk_weight",
      ]),
    );
    expect(cioCards.find((card) => card.id === "target_count_min")?.activation_state).toBe(
      "read_only",
    );

    const missingDirectDependency = structuredClone(artifact);
    const directCard = missingDirectDependency.agents
      .find((agent) => agent.agent === "semiconductor")
      ?.cards.find((card) => card.id === "inventory_to_revenue_risk");
    expect(directCard).toBeDefined();
    if (!directCard) return;
    directCard.evidence_dependencies = [];
    directCard.evidence_dependency_policies = {};
    expect(validateDomainKnobCatalogArtifact(missingDirectDependency)).toContain(
      "domain_card_direct_tool_dependency_missing:inventory_to_revenue_risk",
    );

    const missingDerivedDependency = structuredClone(artifact);
    const derivedCard = missingDerivedDependency.agents
      .find((agent) => agent.agent === "semiconductor")
      ?.cards.find((card) => card.id === "export_control_discount");
    expect(derivedCard).toBeDefined();
    if (!derivedCard) return;
    derivedCard.evidence_dependencies = [];
    derivedCard.evidence_dependency_policies = {};
    expect(validateDomainKnobCatalogArtifact(missingDerivedDependency)).toContain(
      "domain_card_derived_proxy_dependency_missing:export_control_discount",
    );

    const missingRuntimeSource = structuredClone(artifact);
    const runtimeCard = missingRuntimeSource.agents
      .find((agent) => agent.agent === "cro")
      ?.cards.find((card) => card.id === "stop_loss_pct");
    expect(runtimeCard).toBeDefined();
    if (!runtimeCard) return;
    runtimeCard.runtime_input_sources = [];
    runtimeCard.runtime_input_source_policies = {};
    expect(validateDomainKnobCatalogArtifact(missingRuntimeSource)).toContain(
      "domain_card_runtime_source_missing:stop_loss_pct",
    );

    const selfLoopSource = structuredClone(artifact);
    const cioCard = selfLoopSource.agents
      .find((agent) => agent.agent === "cio")
      ?.cards.find((card) => card.id === "min_confidence_to_add");
    expect(cioCard).toBeDefined();
    if (!cioCard) return;
    cioCard.runtime_input_sources = [...cioCard.runtime_input_sources, "candidate_target_state"];
    cioCard.runtime_input_source_policies.candidate_target_state = {
      missing: "disable_card",
      stale: "disable_card",
      source_error: "disable_card",
      empty_confirmed: "invalid",
    };
    expect(validateDomainKnobCatalogArtifact(selfLoopSource)).toContain(
      "domain_card_cio_self_loop_source:min_confidence_to_add:candidate_target_state",
    );

    const incompleteMetric = structuredClone(artifact);
    const metric = incompleteMetric.evaluation_metrics.sector_rank_correlation_20d as unknown as
      | Record<string, unknown>
      | undefined;
    expect(metric).toBeDefined();
    if (!metric) return;
    delete metric.value_convention;
    delete metric.baseline;
    metric.pit_required = false;
    expect(validateDomainKnobCatalogArtifact(incompleteMetric)).toEqual(
      expect.arrayContaining([
        "domain_catalog_metric_value_convention_missing:sector_rank_correlation_20d",
        "domain_catalog_metric_baseline_missing:sector_rank_correlation_20d",
        "domain_catalog_metric_pit_not_required:sector_rank_correlation_20d",
      ]),
    );

    const incompatibleMetric = structuredClone(artifact);
    const slippageMetric = incompatibleMetric.evaluation_metrics.turnover_adjusted_slippage;
    expect(slippageMetric).toBeDefined();
    if (!slippageMetric) return;
    slippageMetric.value_convention = "signed_return";
    expect(validateDomainKnobCatalogArtifact(incompatibleMetric)).toContain(
      "domain_catalog_metric_value_convention_incompatible:turnover_adjusted_slippage",
    );

    const incompatibleHigherMetric = structuredClone(artifact);
    const riskQualityMetric =
      incompatibleHigherMetric.evaluation_metrics.portfolio_risk_quality_20d;
    expect(riskQualityMetric).toBeDefined();
    if (!riskQualityMetric) return;
    riskQualityMetric.value_convention = "nonnegative_loss_magnitude";
    expect(validateDomainKnobCatalogArtifact(incompatibleHigherMetric)).toContain(
      "domain_catalog_metric_value_convention_incompatible:portfolio_risk_quality_20d",
    );

    const incompleteExclusionPolicy = structuredClone(artifact);
    const exclusionMetric = incompleteExclusionPolicy.evaluation_metrics.max_drawdown_after_hold;
    expect(exclusionMetric).toBeDefined();
    if (!exclusionMetric) return;
    exclusionMetric.exclusion_rules = exclusionMetric.exclusion_rules.filter(
      (rule) => rule !== "lookahead_risk",
    );
    expect(validateDomainKnobCatalogArtifact(incompleteExclusionPolicy)).toContain(
      "domain_catalog_metric_exclusion_rule_missing:max_drawdown_after_hold:lookahead_risk",
    );

    const missingExclusionPolicy = structuredClone(artifact);
    const missingExclusionMetric =
      missingExclusionPolicy.evaluation_metrics.max_drawdown_after_hold;
    expect(missingExclusionMetric).toBeDefined();
    if (!missingExclusionMetric) return;
    missingExclusionMetric.exclusion_rules = undefined as unknown as string[];
    expect(validateDomainKnobCatalogArtifact(missingExclusionPolicy)).toEqual(
      expect.arrayContaining([
        "domain_catalog_metric_exclusion_rules_missing:max_drawdown_after_hold",
        "domain_catalog_metric_exclusion_rule_missing:max_drawdown_after_hold:lookahead_risk",
      ]),
    );

    const missingSecondaryMetric = structuredClone(artifact);
    const secondaryCard = missingSecondaryMetric.agents
      .find((agent) => agent.agent === "semiconductor")
      ?.cards.find((card) => card.id === "inventory_cycle_quarters");
    expect(secondaryCard).toBeDefined();
    if (!secondaryCard) return;
    secondaryCard.secondary_metrics = ["unregistered_metric"];
    expect(validateDomainKnobCatalogArtifact(missingSecondaryMetric)).toContain(
      "domain_catalog_card_secondary_metric_unregistered:inventory_cycle_quarters:unregistered_metric",
    );

    const wrongWindowMetric = structuredClone(artifact);
    const windowCard = wrongWindowMetric.agents
      .find((agent) => agent.agent === "semiconductor")
      ?.cards.find((card) => card.id === "inventory_cycle_quarters");
    expect(windowCard).toBeDefined();
    if (!windowCard) return;
    windowCard.secondary_metrics = ["hit_rate_5d"];
    expect(validateDomainKnobCatalogArtifact(wrongWindowMetric)).toContain(
      "domain_card_secondary_metric_window_mismatch:inventory_cycle_quarters:hit_rate_5d:5d:expected:20d",
    );
  });

  it("generates a hash-closed language-neutral evaluation contract", () => {
    const catalog = buildDomainKnobCatalogArtifact();
    const contract = buildDomainKnobEvaluationContractArtifact(catalog);

    expect(validateDomainKnobEvaluationContractArtifact(contract, catalog)).toEqual([]);
    expect(contract.contract_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(contract.catalog_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(contract.card_bindings).toHaveLength(
      catalog.agents.reduce((count, agent) => count + agent.cards.length, 0),
    );
    expect(contract.card_bindings.find((binding) => binding.card_id === "stop_loss_pct")).toEqual(
      expect.objectContaining({
        owner_stage: "cro_review",
        evaluation_metric: "max_drawdown_after_hold",
      }),
    );

    const tampered = structuredClone(contract);
    tampered.card_bindings[0] = {
      ...(tampered.card_bindings[0] as (typeof tampered.card_bindings)[number]),
      evaluation_metric: "missing_metric",
    };
    expect(validateDomainKnobEvaluationContractArtifact(tampered, catalog)).toEqual(
      expect.arrayContaining([
        "evaluation_contract_hash_mismatch:contract_hash",
        `evaluation_contract_card_binding_mismatch:${tampered.card_bindings[0]?.path}`,
      ]),
    );
  });

  it("requires private domain knob value registries and checks projections against them", async () => {
    const repo = makeRoot();
    try {
      const promptsRoot = join(repo.root, "prompts", "mosaic");
      const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "central_bank");
      expect(spec).toBeDefined();
      if (!spec) return;
      const registry = buildDomainKnobValueRegistry(spec, "cohort_default");
      const targetPath = Object.keys(registry.values_by_path).find((path) =>
        path.endsWith("/learnable_parameters/pboc_fed_policy_weight/value"),
      );
      expect(targetPath).toBeDefined();
      if (!targetPath) return;
      registry.values_by_path[targetPath] = 0.35;
      const registryPath = domainKnobValueRegistryPath({
        privatePromptsRoot: promptsRoot,
        cohort: "cohort_default",
        agent: spec.agent,
      });
      mkdirSync(join(repo.root, "registry", "domain_knobs", "cohort_default"), {
        recursive: true,
      });
      writeFileSync(registryPath, `${JSON.stringify(registry, null, 2)}\n`, "utf-8");
      const promptIrPath = promptIrPathForSpec({ privatePromptsRoot: promptsRoot, spec });
      mkdirSync(join(repo.root, "prompt_ir"), { recursive: true });
      writeFileSync(
        promptIrPath,
        renderPromptIrContract(buildPromptIrContract(spec, "cohort_default")),
        "utf-8",
      );
      const knobs = buildRuntimeResearchKnobs(spec, { domainRegistry: registry });
      for (const lang of ["zh", "en"] as const) {
        writePrompt(
          promptsRoot,
          spec.agent,
          spec.layer,
          lang,
          upsertResearchKnobsFence(promptBodyForSpec(spec, lang), knobs),
        );
      }

      const report = await checkResearchKnobsPrompts({
        cohort: "cohort_default",
        privatePromptsRoot: promptsRoot,
        enabledAgents: new Set(["central_bank"]),
      });

      expect(report.ready).toBe(true);
      expect(knobs.thresholds.pboc_fed_policy_weight).toBe(0.35);

      registry.values_by_path[targetPath] = 0.4;
      writeFileSync(registryPath, `${JSON.stringify(registry, null, 2)}\n`, "utf-8");
      const stale = await checkResearchKnobsPrompts({
        cohort: "cohort_default",
        privatePromptsRoot: promptsRoot,
        enabledAgents: new Set(["central_bank"]),
      });
      expect(stale.ready).toBe(false);
      expect(stale.rows.find((row) => row.agent === "central_bank")?.reasons.join("\n")).toContain(
        "domain_card_projection_missing:pboc_fed_policy_weight",
      );
    } finally {
      repo.cleanup();
    }
  });

  it("requires private Prompt IR contracts to match runtime specs", async () => {
    const repo = makeRoot();
    try {
      const promptsRoot = join(repo.root, "prompts", "mosaic");
      const spec = specForAgent("central_bank");
      const registry = buildDomainKnobValueRegistry(spec, "cohort_default");
      const registryPath = domainKnobValueRegistryPath({
        privatePromptsRoot: promptsRoot,
        cohort: "cohort_default",
        agent: spec.agent,
      });
      mkdirSync(join(repo.root, "registry", "domain_knobs", "cohort_default"), {
        recursive: true,
      });
      writeFileSync(registryPath, `${JSON.stringify(registry, null, 2)}\n`, "utf-8");
      const knobs = buildRuntimeResearchKnobs(spec, { domainRegistry: registry });
      for (const lang of ["zh", "en"] as const) {
        writePrompt(
          promptsRoot,
          spec.agent,
          spec.layer,
          lang,
          upsertResearchKnobsFence(promptBodyForSpec(spec, lang), knobs),
        );
      }

      const missing = await checkResearchKnobsPrompts({
        cohort: "cohort_default",
        privatePromptsRoot: promptsRoot,
        enabledAgents: new Set(["central_bank"]),
      });
      expect(missing.ready).toBe(false);
      expect(
        missing.rows.find((row) => row.agent === "central_bank")?.reasons.join("\n"),
      ).toContain("prompt_ir_missing:");

      const promptIr = buildPromptIrContract(spec, "cohort_default");
      promptIr.required_tools = promptIr.required_tools.filter(
        (tool) => tool.name !== "get_pboc_ops",
      );
      const promptIrPath = promptIrPathForSpec({ privatePromptsRoot: promptsRoot, spec });
      mkdirSync(join(repo.root, "prompt_ir"), { recursive: true });
      writeFileSync(promptIrPath, renderPromptIrContract(promptIr), "utf-8");
      const stale = await checkResearchKnobsPrompts({
        cohort: "cohort_default",
        privatePromptsRoot: promptsRoot,
        enabledAgents: new Set(["central_bank"]),
      });
      expect(stale.ready).toBe(false);
      expect(stale.rows.find((row) => row.agent === "central_bank")?.reasons.join("\n")).toContain(
        "prompt_ir_required_tools_mismatch",
      );
    } finally {
      repo.cleanup();
    }
  });

  it("rejects non-concrete and non-canonical mutation target rule ids", async () => {
    const badFence = researchKnobsFence()
      .replace("macro.central_bank.soft.001", "macro.central_bank.primary.001")
      .replace(
        "/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.primary.001",
        "/rule_packs/*/rules/macro.central_bank.primary.001",
      );
    writePrompt(
      fake.root,
      "central_bank",
      "macro",
      "zh",
      `${badFence}\n\n${promptBodyForSpec(specForAgent("central_bank"), "zh")}`,
    );
    writePrompt(
      fake.root,
      "central_bank",
      "macro",
      "en",
      `${badFence}\n\n${promptBodyForSpec(specForAgent("central_bank"), "en")}`,
    );

    const report = await checkResearchKnobsPrompts({
      cohort: "cohort_default",
      promptsRoot: fake.root,
      enabledAgents: new Set(["central_bank"]),
    });

    const row = report.rows.find((item) => item.agent === "central_bank");
    expect(report.ready).toBe(false);
    expect(row?.reasons.join("\n")).toContain("mutation_target_not_concrete");
    expect(row?.reasons.join("\n")).toContain(
      "mutation_target_noncanonical_rule_id:macro.central_bank.primary.001",
    );
  });

  it("fails closed for conflicting-evidence caps without direction adapters", async () => {
    const spec = specForAgent("central_bank");
    const knobs = buildRuntimeResearchKnobs(spec);
    const evidenceKeys = Object.keys(knobs.evidence_registry).filter((key) => key !== "rke_prior");
    expect(evidenceKeys.length).toBeGreaterThanOrEqual(2);
    knobs.confidence_caps.conflicting_signals = {
      cap: 0.65,
      trigger: "conflicting_evidence",
      enforcement: "code",
      required_evidence: evidenceKeys.slice(0, 2),
      conflict_rule: {
        evidence: evidenceKeys.slice(0, 2),
        operator: "opposes",
      },
    };
    for (const lang of ["zh", "en"] as const) {
      writePrompt(
        fake.root,
        spec.agent,
        spec.layer,
        lang,
        upsertResearchKnobsFence(promptBodyForSpec(spec, lang), knobs),
      );
    }

    const report = await checkResearchKnobsPrompts({
      cohort: "cohort_default",
      promptsRoot: fake.root,
      enabledAgents: new Set(["central_bank"]),
    });

    const row = report.rows.find((item) => item.agent === "central_bank");
    expect(report.ready).toBe(false);
    expect(row?.reasons.join("\n")).toContain(
      "conflicting_evidence_direction_adapter_missing:conflicting_signals",
    );
  });
});

function domainProjectionValue(knobs: ResearchKnobs, card: DomainKnobCard): unknown {
  if (card.projection_bucket === "lookbacks") return knobs.lookbacks[card.id];
  if (card.projection_bucket === "thresholds") return knobs.thresholds[card.id];
  if (card.projection_bucket === "evidence_weights") return knobs.evidence_weights[card.id];
  if (card.projection_bucket === "confidence_caps") return knobs.confidence_caps[card.id]?.cap;
  const value = typeof card.default === "string" ? card.default : card.id;
  return knobs.tie_breaks.includes(value) ? value : undefined;
}
