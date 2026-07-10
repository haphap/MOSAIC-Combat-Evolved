import { describe, expect, it } from "vitest";
import { z } from "zod";
import { emptyLayer4RuntimeState } from "../src/agents/decision/layer4_runtime.js";
import {
  applyResearchKnobCaps,
  assertResearchKnobCappedOutputSchema,
  assertResearchKnobsParity,
  buildResearchKnobsSnapshot,
  canonicalResearchKnobs,
  isResearchKnobsStageEnabled,
  parseResearchKnobsPrompt,
  type ResearchKnobs,
  ResearchKnobsSchema,
  researchKnobsEnabledAgentStages,
} from "../src/agents/helpers/research_knobs.js";
import { resolveRuntimeSourceStatusesForAgent } from "../src/agents/helpers/runtime_sources.js";
import { buildRuntimeResearchKnobs } from "../src/agents/prompts/research_knobs_projection.js";
import { RUNTIME_AGENT_SPECS } from "../src/agents/prompts/runtime_agent_spec.js";

function knobs(): ResearchKnobs {
  return {
    schema_version: "research_knobs_v1",
    layer: "macro",
    agent: "macro.central_bank",
    research_scope: {
      must_cover: ["liquidity_regime"],
      must_not_cover: ["final_portfolio_sizing"],
    },
    prediction_targets: [
      {
        id: "liquidity_regime_20d",
        target_variable: "liquidity_regime",
        horizon: "20d",
        allowed_outputs: ["positive", "neutral", "negative"],
      },
    ],
    evidence_registry: {
      pboc_liquidity: {
        tool: "get_pboc_ops",
        metric: "pboc_net_injection_7d",
        current_data: true,
        primary: true,
      },
    },
    evidence_weights: {
      pboc_liquidity: 1,
    },
    lookbacks: {
      net_injection_window_days: 7,
    },
    thresholds: {},
    confidence_caps: {
      missing_current_data: {
        cap: 0.55,
        trigger: "missing_required_evidence",
        enforcement: "code",
        required_evidence: ["pboc_liquidity"],
      },
      fallback_primary_tool: {
        cap: 0.6,
        trigger: "primary_tool_failed_or_fallback",
        enforcement: "code",
        required_evidence: ["pboc_liquidity"],
      },
    },
    tie_breaks: [],
    mutation_targets: [
      {
        path: "/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/pboc_liquidity_weight/value",
        type: "number",
        min: 0,
        max: 1,
      },
    ],
  };
}

describe("research knob cap enforcement", () => {
  it("uses agent-stage enablement with an explicit legacy migration path", () => {
    const explicit = researchKnobsEnabledAgentStages(
      "cio:cio_proposal,cro:cro_review",
      "ignored_legacy_agent",
    );
    expect(isResearchKnobsStageEnabled("cio", "cio_proposal", explicit)).toBe(true);
    expect(isResearchKnobsStageEnabled("cio", "cio_final", explicit)).toBe(false);

    const migrated = researchKnobsEnabledAgentStages(undefined, "cio,central_bank");
    expect(isResearchKnobsStageEnabled("cio", "cio_final", migrated)).toBe(true);
    expect(isResearchKnobsStageEnabled("central_bank", "agent_run", migrated)).toBe(true);
  });

  it("rejects extra fields in the prompt projection schema", () => {
    const text = `\`\`\`research-knobs
research-knobs:
  schema_version: research_knobs_v1
  layer: macro
  agent: macro.central_bank
  unexpected_field: should_fail
  research_scope:
    must_cover: [liquidity_regime]
    must_not_cover: [final_portfolio_sizing]
  prediction_targets:
    - id: liquidity_regime_20d
      target_variable: liquidity_regime
      horizon: 20d
      allowed_outputs: [positive, neutral, negative]
  evidence_registry:
    pboc_liquidity:
      tool: get_pboc_ops
      metric: pboc_net_injection_7d
      current_data: true
      primary: true
  evidence_weights:
    pboc_liquidity: 1.0
  lookbacks: {}
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

    expect(() => parseResearchKnobsPrompt(text)).toThrow(/unrecognized key/i);
  });

  it("only accepts a single research-knobs fence with the v1 schema", () => {
    const fence = `\`\`\`research-knobs
research-knobs:
  schema_version: research_knobs_v1
  layer: macro
  agent: macro.central_bank
  research_scope:
    must_cover: [liquidity_regime]
    must_not_cover: [final_portfolio_sizing]
  prediction_targets:
    - id: liquidity_regime_20d
      target_variable: liquidity_regime
      horizon: 20d
      allowed_outputs: [positive, neutral, negative]
  evidence_registry:
    pboc_liquidity:
      tool: get_pboc_ops
      metric: pboc_net_injection_7d
      current_data: true
      primary: true
  evidence_weights:
    pboc_liquidity: 1.0
  lookbacks: {}
  thresholds: {}
  confidence_caps:
    missing_current_data:
      cap: 0.55
      trigger: missing_required_evidence
      enforcement: code
      required_evidence: [pboc_liquidity]
  tie_breaks: []
  mutation_targets: []
\`\`\``;

    expect(() => parseResearchKnobsPrompt("```yaml\nresearch-knobs: {}\n```")).toThrow(
      /expected exactly one research-knobs fence/,
    );
    expect(() => parseResearchKnobsPrompt(`${fence}\n\n${fence}`)).toThrow(
      /expected exactly one research-knobs fence, found 2/,
    );
    expect(() =>
      parseResearchKnobsPrompt(fence.replace("research_knobs_v1", "research_knobs_v2")),
    ).toThrow(/research_knobs_v1/);
  });

  it("canonicalizes set-like lists for zh/en parity without reordering ordered lists", () => {
    const left = knobs();
    const right = knobs();
    const target = right.prediction_targets[0];
    expect(target).toBeDefined();
    if (!target) return;
    right.research_scope.must_cover = [...left.research_scope.must_cover].reverse();
    right.prediction_targets[0] = {
      ...target,
      allowed_outputs: [...target.allowed_outputs].reverse(),
    };
    expect(() => assertResearchKnobsParity(left, right)).not.toThrow();

    right.tie_breaks = ["second", "first"];
    left.tie_breaks = ["first", "second"];
    expect(canonicalResearchKnobs(right)).not.toEqual(canonicalResearchKnobs(left));
    expect(() => assertResearchKnobsParity(left, right)).toThrow(/parity mismatch/);
  });

  it("requires an explicit conflict rule for conflicting-evidence caps", () => {
    const bad = knobs();
    bad.confidence_caps.conflicting_signals = {
      cap: 0.65,
      trigger: "conflicting_evidence",
      enforcement: "code",
      required_evidence: ["pboc_liquidity"],
    };

    expect(() => ResearchKnobsSchema.parse(bad)).toThrow(/conflict_rule/);
  });

  it("clamps top-level and nested confidence when required current data is missing", () => {
    const snapshot = buildResearchKnobsSnapshot({
      agent: "central_bank",
      cohort: "cohort_default",
      knobs: knobs(),
    });

    const result = applyResearchKnobCaps(
      {
        confidence: 0.82,
        evidence_ledger: [{ claim: "liquidity supportive", confidence_impact: 0.7 }],
      },
      snapshot,
      {
        toolStatuses: [],
      },
    );

    expect(result.output.confidence).toBe(0.55);
    expect(result.output.evidence_ledger[0]?.confidence_impact).toBe(0.55);
    expect(result.audit.pre_cap_confidence).toBe(0.82);
    expect(result.audit.post_cap_confidence).toBe(0.55);
    expect(result.audit.fired_cap_ids).toContain("missing_current_data");
    expect(result.audit.knob_snapshot_hash).toMatch(/^sha256:/);
    expect(result.audit.missing_scopes).toContain("tool:get_pboc_ops:missing");
  });

  it("revalidates capped output against the agent schema while preserving runtime audit", () => {
    const snapshot = buildResearchKnobsSnapshot({
      agent: "central_bank",
      cohort: "cohort_default",
      knobs: knobs(),
    });
    const result = applyResearchKnobCaps(
      {
        confidence: 0.82,
        evidence_ledger: [{ confidence_impact: 0.7 }],
      },
      snapshot,
      {
        toolStatuses: [],
      },
    );
    const schema = z
      .object({
        confidence: z.number().max(0.55),
        evidence_ledger: z.array(z.object({ confidence_impact: z.number().max(0.55) })),
      })
      .strict();
    const tooStrictSchema = z
      .object({
        confidence: z.number().max(0.5),
        evidence_ledger: z.array(z.object({ confidence_impact: z.number().max(0.5) })),
      })
      .strict();

    const output = assertResearchKnobCappedOutputSchema(
      result.output,
      schema,
      "central_bank",
    ) as typeof result.output & { verified_knob_audit: unknown };

    expect(output.verified_knob_audit).toBeDefined();
    expect(() =>
      assertResearchKnobCappedOutputSchema(result.output, tooStrictSchema, "central_bank"),
    ).toThrow(/research_knob_capped_output_schema_failed:central_bank/);
  });

  it("uses the strictest cap when multiple policies fire", () => {
    const snapshot = buildResearchKnobsSnapshot({
      agent: "central_bank",
      cohort: "cohort_default",
      knobs: knobs(),
    });

    const result = applyResearchKnobCaps({ confidence: 0.9 }, snapshot, {
      toolStatuses: [
        {
          name: "get_pboc_ops",
          called: true,
          failed: false,
          missing: false,
          fallback: true,
          cache_hit: false,
        },
      ],
    });

    expect(result.output.confidence).toBe(0.55);
    expect(result.audit.fired_cap_ids).toEqual(["missing_current_data", "fallback_primary_tool"]);
    expect(result.audit.fallback_scopes).toContain("tool:get_pboc_ops:fallback");
  });

  it("builds visible domain knobs from active runtime source statuses only", () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "cio");
    expect(spec).toBeDefined();
    if (!spec) return;
    const runtimeKnobs = buildRuntimeResearchKnobs(spec);
    const disabled = buildResearchKnobsSnapshot({
      agent: "cio",
      cohort: "cohort_default",
      knobs: runtimeKnobs,
    });

    expect(disabled.consumptionSnapshot.active_knobs).toHaveLength(0);
    expect(disabled.consumptionSnapshot.disabled_knobs.length).toBeGreaterThan(0);
    expect(
      JSON.parse(disabled.visibleContract.split("\n\n")[1] ?? "{}").thresholds,
    ).not.toHaveProperty("min_confidence_to_add");

    const active = buildResearchKnobsSnapshot({
      agent: "cio",
      cohort: "cohort_default",
      knobs: runtimeKnobs,
      runtimeSourceStatuses: [
        { source_id: "current_position_snapshot", scope: "account:paper", status: "loaded" },
        { source_id: "current_market_data", scope: "ticker:600519.SH", status: "loaded" },
        { source_id: "previous_target_state", scope: "account:paper", status: "loaded" },
        { source_id: "upstream_agent_outputs", scope: "agent:macro", status: "loaded" },
        { source_id: "position_thesis_state", scope: "ticker:600519.SH", status: "loaded" },
        { source_id: "position_review_state", scope: "account:paper", status: "loaded" },
        { source_id: "candidate_target_state", scope: "run:test", status: "loaded" },
        { source_id: "cro_review_state", scope: "run:test", status: "loaded" },
        { source_id: "execution_feasibility_state", scope: "run:test", status: "loaded" },
        { source_id: "mirofish_context", scope: "context:test", status: "loaded" },
      ],
    });

    expect(active.consumptionSnapshot.disabled_knobs).toHaveLength(0);
    expect(active.visibleContract).toContain('"min_confidence_to_add"');
    expect(active.visibleContract).toContain('"active_knobs"');
  });

  it("filters CIO cards by explicit proposal and final stages", () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "cio");
    expect(spec).toBeDefined();
    if (!spec) return;
    const knobs = buildRuntimeResearchKnobs(spec);
    const proposal = buildResearchKnobsSnapshot({
      agent: "cio",
      cohort: "cohort_default",
      stage: "cio_proposal",
      knobs,
      runtimeSourceStatuses: [
        { source_id: "current_position_snapshot", scope: "account:paper", status: "loaded" },
        { source_id: "current_market_data", scope: "ticker:600519.SH", status: "loaded" },
        { source_id: "previous_target_state", scope: "account:paper", status: "loaded" },
        { source_id: "upstream_agent_outputs", scope: "agent:macro", status: "loaded" },
        { source_id: "position_thesis_state", scope: "ticker:600519.SH", status: "loaded" },
      ],
    });
    const final = buildResearchKnobsSnapshot({
      agent: "cio",
      cohort: "cohort_default",
      stage: "cio_final",
      knobs,
      runtimeSourceStatuses: [
        { source_id: "current_position_snapshot", scope: "account:paper", status: "loaded" },
        { source_id: "current_market_data", scope: "ticker:600519.SH", status: "loaded" },
        { source_id: "candidate_target_state", scope: "run:test", status: "loaded" },
        { source_id: "cro_review_state", scope: "run:test", status: "loaded" },
        { source_id: "execution_feasibility_state", scope: "run:test", status: "loaded" },
        { source_id: "mirofish_context", scope: "context:test", status: "loaded" },
      ],
    });

    expect(proposal.stage).toBe("cio_proposal");
    expect(proposal.consumptionSnapshot.active_knobs.map((card) => card.card_id)).toEqual(
      expect.arrayContaining([
        "stale_thesis_days",
        "rebalance_drift_pct",
        "min_confidence_to_add",
        "min_confidence_to_hold",
      ]),
    );
    expect(proposal.visibleContract).not.toContain('"mirofish_portfolio_stress_weight"');
    expect(final.stage).toBe("cio_final");
    expect(final.consumptionSnapshot.active_knobs.map((card) => card.card_id)).toEqual(
      expect.arrayContaining([
        "mirofish_portfolio_stress_weight",
        "mirofish_exit_regret_penalty",
        "mirofish_min_scenario_agreement_to_add",
        "mirofish_override_hurdle",
      ]),
    );
    expect(final.visibleContract).not.toContain('"min_confidence_to_add"');
  });

  it("disables drift knobs when previous target state is empty-confirmed", () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "cio");
    expect(spec).toBeDefined();
    if (!spec) return;
    const snapshot = buildResearchKnobsSnapshot({
      agent: "cio",
      cohort: "cohort_default",
      knobs: buildRuntimeResearchKnobs(spec),
      runtimeSourceStatuses: [
        { source_id: "current_position_snapshot", scope: "account:paper", status: "loaded" },
        { source_id: "current_market_data", scope: "ticker:600519.SH", status: "loaded" },
        { source_id: "previous_target_state", scope: "account:paper", status: "empty_confirmed" },
        { source_id: "upstream_agent_outputs", scope: "agent:macro", status: "loaded" },
        { source_id: "position_thesis_state", scope: "ticker:600519.SH", status: "loaded" },
        { source_id: "position_review_state", scope: "account:paper", status: "loaded" },
        { source_id: "mirofish_context", scope: "context:test", status: "loaded" },
      ],
    });
    const visible = JSON.parse(snapshot.visibleContract.split("\n\n")[1] ?? "{}");

    expect(snapshot.consumptionSnapshot.disabled_knobs).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          card_id: "rebalance_drift_pct",
          disabled_reason: expect.stringContaining("previous_target_state:empty_confirmed"),
        }),
      ]),
    );
    expect(snapshot.consumptionSnapshot.active_knobs).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ card_id: "rebalance_drift_pct" })]),
    );
    expect(visible.thresholds).not.toHaveProperty("rebalance_drift_pct");
  });

  it("rejects declared influence ids for disabled runtime-source cards", () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "cio");
    expect(spec).toBeDefined();
    if (!spec) return;
    const snapshot = buildResearchKnobsSnapshot({
      agent: "cio",
      cohort: "cohort_default",
      knobs: buildRuntimeResearchKnobs(spec),
      runtimeSourceStatuses: [
        { source_id: "current_position_snapshot", scope: "account:paper", status: "loaded" },
        { source_id: "current_market_data", scope: "ticker:600519.SH", status: "loaded" },
        { source_id: "previous_target_state", scope: "account:paper", status: "empty_confirmed" },
        { source_id: "upstream_agent_outputs", scope: "agent:macro", status: "loaded" },
        { source_id: "position_thesis_state", scope: "ticker:600519.SH", status: "loaded" },
        { source_id: "position_review_state", scope: "account:paper", status: "loaded" },
        { source_id: "mirofish_context", scope: "context:test", status: "loaded" },
      ],
    });

    expect(() =>
      applyResearchKnobCaps(
        { confidence: 0.8, declared_knob_influence_ids: ["rebalance_drift_pct"] },
        snapshot,
        { toolStatuses: [] },
      ),
    ).toThrow(/disabled_knob_influence_declared:rebalance_drift_pct/);
  });

  it("keeps direct-tool domain knobs active before post-run evidence dependency checks", () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "central_bank");
    expect(spec).toBeDefined();
    if (!spec) return;
    const snapshot = buildResearchKnobsSnapshot({
      agent: "central_bank",
      cohort: "cohort_default",
      knobs: buildRuntimeResearchKnobs(spec),
    });

    expect(snapshot.consumptionSnapshot.active_knobs.length).toBeGreaterThan(0);
    expect(snapshot.consumptionSnapshot.disabled_knobs).toHaveLength(0);
    expect(snapshot.visibleContract).toContain('"pboc_fed_policy_weight"');
  });

  it("uses dependency min coverage when deciding unsupported knob influence", () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "central_bank");
    expect(spec).toBeDefined();
    if (!spec) return;
    const snapshot = buildResearchKnobsSnapshot({
      agent: "central_bank",
      cohort: "cohort_default",
      knobs: buildRuntimeResearchKnobs(spec),
    });
    const output = {
      confidence: 0.8,
      declared_knob_influence_ids: ["pboc_fed_policy_weight"],
    };

    const sufficient = applyResearchKnobCaps(output, snapshot, {
      toolStatuses: [],
      evidenceDependencyStatuses: [
        {
          card_id: "pboc_fed_policy_weight",
          dependency_id: "macro.central_bank.pboc_fed_policy_weight.primary",
          evidence_key: "pboc_ops",
          scope: "cohort:cohort_default",
          metric_id: "pboc_ops_current",
          status: "partial_loaded",
          coverage_ratio: 0.8,
          min_scope_coverage: 0.7,
        },
      ],
    });
    const insufficient = applyResearchKnobCaps(output, snapshot, {
      toolStatuses: [],
      evidenceDependencyStatuses: [
        {
          card_id: "pboc_fed_policy_weight",
          dependency_id: "macro.central_bank.pboc_fed_policy_weight.primary",
          evidence_key: "pboc_ops",
          scope: "cohort:cohort_default",
          metric_id: "pboc_ops_current",
          status: "partial_loaded",
          coverage_ratio: 0.6,
          min_scope_coverage: 0.7,
        },
      ],
    });

    expect(sufficient.audit.unsupported_knob_influence_ids).toEqual([]);
    expect(insufficient.audit.unsupported_knob_influence_ids).toEqual(["pboc_fed_policy_weight"]);
  });

  it("derives dependency statuses per dependency metric", () => {
    const sourceKnobs = knobs();
    sourceKnobs.thresholds = { dual_metric_card: 0.2 };
    sourceKnobs.projection_metadata = {
      domain_knob_catalog: {
        cards: [
          {
            id: "dual_metric_card",
            path: "/rule_packs/macro.central_bank.runtime.v1/rules/macro.central_bank.soft.001/learnable_parameters/dual_metric_card/value",
            projection_bucket: "thresholds",
            runtime_input_sources: [],
            runtime_input_source_policies: {},
            evidence_dependencies: [
              {
                dependency_id: "dual_metric_card.primary",
                evidence_key: "pboc_liquidity",
                tool: "get_pboc_ops",
                metric_ids: ["metric_a", "metric_b"],
                min_scope_coverage: 1,
              },
            ],
            evidence_dependency_policies: {
              "dual_metric_card.primary": {
                missing: "exclude_sample_and_cap_if_required",
                stale: "exclude_sample_and_cap_if_required",
                fallback: "exclude_sample_and_cap_if_required",
                tool_failed: "exclude_sample_and_cap_if_required",
                partial_loaded: "exclude_sample_only",
                loaded: "allow",
              },
            },
          },
        ],
      },
    };
    const snapshot = buildResearchKnobsSnapshot({
      agent: "central_bank",
      cohort: "cohort_default",
      knobs: sourceKnobs,
    });

    const result = applyResearchKnobCaps({ confidence: 0.8 }, snapshot, {
      toolStatuses: [],
    });

    expect(result.audit.evidence_dependency_status_summary.missing).toBe(2);
  });

  it("distinguishes in-run derived scope empty, fallback, budget, and partial states", () => {
    const sourceKnobs = knobs();
    sourceKnobs.evidence_registry = {
      etf_holdings: {
        tool: "get_etf_holdings",
        metric: "etf_holdings_current",
        current_data: true,
        primary: true,
      },
      stock_data: {
        tool: "get_stock_data",
        metric: "stock_data_current",
        current_data: true,
        primary: false,
      },
    };
    sourceKnobs.evidence_weights = { etf_holdings: 1 };
    sourceKnobs.thresholds = { in_run_card: 0.2 };
    sourceKnobs.projection_metadata = {
      domain_knob_catalog: {
        cards: [
          {
            id: "in_run_card",
            path: "/rule_packs/macro.central_bank.runtime.v1/rules/macro.central_bank.soft.001/learnable_parameters/in_run_card/value",
            projection_bucket: "thresholds",
            runtime_input_sources: [],
            runtime_input_source_policies: {},
            evidence_dependencies: [
              {
                dependency_id: "macro.central_bank.in_run_card.candidate_validation",
                evidence_key: "stock_data",
                tool: "get_stock_data",
                metric_ids: ["close"],
                min_scope_coverage: 0.8,
                scope_resolution: "in_run_tool_derived",
                scope_source_tool: "get_etf_holdings",
                max_scope_count: 2,
                min_scope_count: 1,
                empty_scope_behavior: "exclude_sample",
              },
            ],
            evidence_dependency_policies: {},
          },
        ],
      },
    };
    const snapshot = buildResearchKnobsSnapshot({
      agent: "central_bank",
      cohort: "cohort_default",
      knobs: sourceKnobs,
    });
    const source = {
      name: "get_etf_holdings",
      called: true,
      failed: false,
      missing: false,
      fallback: false,
      cache_hit: false,
    };
    const validator = {
      name: "get_stock_data",
      called: true,
      failed: false,
      missing: false,
      fallback: false,
      cache_hit: false,
    };

    const empty = applyResearchKnobCaps({ confidence: 0.8 }, snapshot, {
      toolStatuses: [{ ...source, args: { candidate_scopes: [] } }, validator],
    });
    const fallback = applyResearchKnobCaps({ confidence: 0.8 }, snapshot, {
      toolStatuses: [
        { ...source, fallback: true, args: { candidate_scopes: ["ticker:A"] } },
        validator,
      ],
    });
    const budget = applyResearchKnobCaps({ confidence: 0.8 }, snapshot, {
      toolStatuses: [
        { ...source, args: { candidate_scopes: ["ticker:A", "ticker:B", "ticker:C"] } },
        { ...validator, args: { loaded_scopes: ["ticker:A", "ticker:B"] } },
      ],
    });
    const partial = applyResearchKnobCaps({ confidence: 0.8 }, snapshot, {
      toolStatuses: [
        { ...source, args: { candidate_scopes: ["ticker:A", "ticker:B"] } },
        { ...validator, args: { loaded_scopes: ["ticker:A"], missing_scopes: ["ticker:B"] } },
      ],
    });

    expect(empty.audit.evidence_dependency_status_summary.partial_loaded).toBe(1);
    expect(empty.audit.evidence_dependency_status_summary.missing).toBe(0);
    expect(fallback.audit.evidence_dependency_status_summary.fallback).toBe(1);
    expect(budget.audit.evidence_dependency_status_summary.partial_loaded).toBe(1);
    expect(budget.audit.coverage_ratio).toBeCloseTo(2 / 3);
    expect(partial.audit.evidence_dependency_status_summary.partial_loaded).toBe(1);
    expect(partial.audit.coverage_ratio).toBeCloseTo(0.5);
  });

  it("resolves scoped position runtime sources without inventing missing market data", () => {
    const emptyState = {
      active_cohort: "cohort_default",
      as_of_date: "2026-07-09",
      trace_id: "run-1",
      layer1_outputs: {},
      layer2_outputs: {},
      layer3_outputs: {},
      current_positions: {
        snapshot_status: "empty_confirmed",
        position_source: "empty_confirmed",
        source_error_code: null,
        position_snapshot_hash: "sha256:empty_positions",
        positions: [],
      },
      portfolio_actions: [],
    } as unknown as Parameters<typeof resolveRuntimeSourceStatusesForAgent>[0];
    const emptyStatuses = resolveRuntimeSourceStatusesForAgent(emptyState, "cio");

    expect(emptyStatuses).toContainEqual(
      expect.objectContaining({
        source_id: "current_market_data",
        scope: "ticker_scope:empty",
        status: "loaded",
      }),
    );
    expect(emptyStatuses).toContainEqual(
      expect.objectContaining({
        source_id: "current_position_snapshot",
        status: "empty_confirmed",
        snapshot_hash: "sha256:empty_positions",
      }),
    );
    expect(emptyStatuses).toContainEqual(
      expect.objectContaining({
        source_id: "upstream_agent_outputs",
        scope: expect.stringContaining("agent:central_bank|"),
        status: "missing",
        error_code: "upstream_agent_output_missing:central_bank",
      }),
    );

    const missingState = {
      ...emptyState,
      current_positions: {
        snapshot_status: "missing",
        position_source: "cli_fixture",
        source_error_code: "fixture_unavailable",
        positions: [],
      },
      portfolio_actions: [],
    } as unknown as Parameters<typeof resolveRuntimeSourceStatusesForAgent>[0];
    const missingStatuses = resolveRuntimeSourceStatusesForAgent(missingState, "cio");
    expect(missingStatuses).toContainEqual(
      expect.objectContaining({
        source_id: "current_position_snapshot",
        status: "missing",
        error_code: "fixture_unavailable",
      }),
    );
    expect(missingStatuses).toContainEqual(
      expect.objectContaining({
        source_id: "current_market_data",
        scope: "ticker_scope:unknown",
        status: "missing",
        error_code: "current_market_data_unresolved_without_positions",
      }),
    );

    const loadedState = {
      ...emptyState,
      current_positions: {
        snapshot_status: "loaded",
        position_source: "cli_fixture",
        source_error_code: null,
        position_snapshot_hash: "sha256:positions",
        positions: [
          {
            ticker: "600519.SH",
            current_weight: 0.08,
            cost_basis: 100,
            market_price: 105,
            unrealized_pnl_pct: 0.05,
            holding_days: 9,
            entry_date: "2026-06-30",
            source_agent: "munger",
            entry_thesis_id: "thesis-600519",
            last_review_date: "2026-07-08",
          },
        ],
      },
      portfolio_actions: [
        {
          ticker: "000001.SZ",
          action: "BUY",
          target_weight: 0.03,
          holding_period: "1M",
          dissent_notes: "",
        },
      ],
      layer4_outputs: {
        runtime: {
          ...emptyLayer4RuntimeState(),
          candidate_target_state: {
            candidate_target_hash: "sha256:candidate",
            portfolio_actions: [
              {
                ticker: "000001.SZ",
                action: "BUY",
                target_weight: 0.03,
                holding_period: "1M",
                dissent_notes: "",
              },
            ],
          },
          position_review_state: { position_review_hash: "sha256:reviews" },
          cro_review_state: { review_hash: "sha256:cro" },
          execution_feasibility_state: { feasibility_hash: "sha256:execution" },
          resolved_source_statuses: [
            {
              source_id: "current_market_data",
              scope: "ticker:600519.SH",
              status: "loaded",
              as_of: "2026-07-09",
              snapshot_hash: "sha256:market-600519",
            },
          ],
        },
      },
    } as unknown as Parameters<typeof resolveRuntimeSourceStatusesForAgent>[0];
    const loadedStatuses = resolveRuntimeSourceStatusesForAgent(loadedState, "cio");

    expect(loadedStatuses).toContainEqual(
      expect.objectContaining({
        source_id: "current_market_data",
        scope: "ticker:600519.SH",
        snapshot_hash: expect.stringMatching(/^sha256:/),
      }),
    );
    expect(loadedStatuses).toContainEqual(
      expect.objectContaining({
        source_id: "current_market_data",
        scope: "ticker:000001.SZ",
        status: "missing",
        error_code: "current_market_data_adapter_not_resolved",
      }),
    );
    expect(loadedStatuses).toContainEqual(
      expect.objectContaining({ source_id: "position_thesis_state", scope: "ticker:600519.SH" }),
    );
    const proposalStatuses = resolveRuntimeSourceStatusesForAgent(
      loadedState,
      "cio",
      "cio_proposal",
    );
    expect(proposalStatuses.some((status) => status.source_id === "candidate_target_state")).toBe(
      false,
    );
    const finalStatuses = resolveRuntimeSourceStatusesForAgent(loadedState, "cio", "cio_final");
    expect(finalStatuses).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          source_id: "candidate_target_state",
          status: "loaded",
          snapshot_hash: "sha256:candidate",
        }),
        expect.objectContaining({ source_id: "cro_review_state", status: "loaded" }),
        expect.objectContaining({ source_id: "execution_feasibility_state", status: "loaded" }),
      ]),
    );
  });

  it("marks low-quality upstream outputs as source errors for downstream runtime knobs", () => {
    const state = {
      active_cohort: "cohort_default",
      as_of_date: "2026-07-09",
      trace_id: "run-1",
      layer1_outputs: {
        central_bank: {
          agent: "central_bank",
          confidence: 0.4,
          verified_knob_audit: {
            fired_cap_ids: ["missing_current_data"],
          },
        },
        china: {
          agent: "china",
          confidence: 0,
          verified_knob_audit: {
            fired_cap_ids: [],
          },
        },
        dollar: {
          agent: "dollar",
          confidence: 0.7,
          verified_knob_audit: {
            fired_cap_ids: [],
          },
        },
      },
      layer2_outputs: {},
      layer3_outputs: {},
      current_positions: {
        snapshot_status: "empty_confirmed",
        position_source: "empty_confirmed",
        source_error_code: null,
        position_snapshot_hash: "sha256:empty_positions",
        positions: [],
      },
      portfolio_actions: [],
    } as unknown as Parameters<typeof resolveRuntimeSourceStatusesForAgent>[0];

    const statuses = resolveRuntimeSourceStatusesForAgent(state, "cio");

    expect(statuses).toContainEqual(
      expect.objectContaining({
        source_id: "upstream_agent_outputs",
        scope: expect.stringContaining("agent:central_bank|"),
        status: "source_error",
        error_code: "upstream_agent_output_fired_caps:central_bank:missing_current_data",
        snapshot_hash: expect.stringMatching(/^sha256:/),
      }),
    );
    expect(statuses).toContainEqual(
      expect.objectContaining({
        source_id: "upstream_agent_outputs",
        scope: expect.stringContaining("agent:china|"),
        status: "source_error",
        error_code: "upstream_agent_output_low_confidence:china",
      }),
    );
    expect(statuses).toContainEqual(
      expect.objectContaining({
        source_id: "upstream_agent_outputs",
        scope: expect.stringContaining("agent:dollar|"),
        status: "loaded",
      }),
    );
  });

  it("caps required runtime-state evidence when scoped runtime source is missing", () => {
    const sourceKnobs = knobs();
    sourceKnobs.evidence_registry = {
      upstream_context: {
        source: "daily_cycle_state",
        metric: "upstream_agent_outputs",
        current_data: true,
        primary: true,
      },
    };
    sourceKnobs.evidence_weights = { upstream_context: 1 };
    const missingCap = sourceKnobs.confidence_caps.missing_current_data;
    const fallbackCap = sourceKnobs.confidence_caps.fallback_primary_tool;
    expect(missingCap).toBeDefined();
    expect(fallbackCap).toBeDefined();
    if (!missingCap || !fallbackCap) return;
    missingCap.required_evidence = ["upstream_context"];
    fallbackCap.required_evidence = ["upstream_context"];
    const snapshot = buildResearchKnobsSnapshot({
      agent: "cio",
      cohort: "cohort_default",
      knobs: sourceKnobs,
    });

    const missing = applyResearchKnobCaps({ confidence: 0.9 }, snapshot, {
      toolStatuses: [],
      runtimeSourceStatuses: [],
    });
    const sourceMissing = applyResearchKnobCaps({ confidence: 0.9 }, snapshot, {
      toolStatuses: [],
      runtimeSourceStatuses: [
        {
          source_id: "upstream_agent_outputs",
          scope: "agent:macro",
          status: "missing",
          error_code: "upstream_missing",
        },
      ],
    });
    const loaded = applyResearchKnobCaps({ confidence: 0.9 }, snapshot, {
      toolStatuses: [],
      runtimeSourceStatuses: [
        { source_id: "upstream_agent_outputs", scope: "agent:macro", status: "loaded" },
        {
          source_id: "mirofish_context",
          scope: "context:sha256:test_context",
          status: "loaded",
          snapshot_hash: "sha256:test_context",
        },
      ],
    });

    expect(missing.output.confidence).toBe(0.55);
    expect(missing.audit.runtime_source_status_summary.missing).toBe(0);
    expect(missing.audit.fired_cap_ids).toContain("missing_current_data");
    expect(missing.audit.missing_scopes).toContain("upstream_agent_outputs:*:missing");
    expect(sourceMissing.output.confidence).toBe(0.55);
    expect(sourceMissing.audit.runtime_source_status_summary.missing).toBe(1);
    expect(sourceMissing.audit.missing_scopes).toContain(
      "upstream_agent_outputs:agent:macro:missing",
    );
    expect(loaded.output.confidence).toBe(0.9);
    expect(loaded.audit.fired_cap_ids).toEqual([]);
    expect(loaded.audit.runtime_source_status_summary.loaded).toBe(2);
    expect(loaded.audit.runtime_source_statuses).toContainEqual(
      expect.objectContaining({
        source_id: "mirofish_context",
        scope: "context:sha256:test_context",
        snapshot_hash: "sha256:test_context",
      }),
    );
  });

  it("adds verified knob audit and marks unsupported declared influence ids", () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "central_bank");
    expect(spec).toBeDefined();
    if (!spec) return;
    const snapshot = buildResearchKnobsSnapshot({
      agent: "central_bank",
      cohort: "cohort_default",
      knobs: buildRuntimeResearchKnobs(spec),
    });

    const result = applyResearchKnobCaps(
      {
        confidence: 0.7,
        declared_knob_influence_ids: ["pboc_fed_policy_weight", "missing_card"],
      },
      snapshot,
      {
        toolStatuses: [
          {
            name: "get_pboc_ops",
            called: true,
            failed: false,
            missing: false,
            fallback: false,
            cache_hit: false,
          },
        ],
        evidenceDependencyStatuses: [
          {
            card_id: "pboc_fed_policy_weight",
            dependency_id: "macro.central_bank.pboc_fed_policy_weight.primary",
            evidence_key: "pboc_ops",
            scope: "cohort_default",
            status: "tool_failed",
            coverage_ratio: 0,
          },
        ],
      },
    );
    const output = result.output as typeof result.output & {
      verified_knob_audit: { unsupported_knob_influence_ids: string[] };
    };

    expect(result.audit.unsupported_knob_influence_ids).toEqual([
      "pboc_fed_policy_weight",
      "missing_card",
    ]);
    expect(result.audit.sample_exclusion_reason).toContain("unsupported_knob_influence");
    expect(output.verified_knob_audit.unsupported_knob_influence_ids).toEqual(
      result.audit.unsupported_knob_influence_ids,
    );
  });

  it("derives post-run evidence dependency statuses from tool statuses", () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "central_bank");
    expect(spec).toBeDefined();
    if (!spec) return;
    const snapshot = buildResearchKnobsSnapshot({
      agent: "central_bank",
      cohort: "cohort_default",
      knobs: buildRuntimeResearchKnobs(spec),
    });

    const result = applyResearchKnobCaps(
      {
        confidence: 0.7,
        declared_knob_influence_ids: ["pboc_fed_policy_weight"],
      },
      snapshot,
      {
        toolStatuses: [],
      },
    );

    expect(result.audit.evidence_dependency_status_summary.missing).toBeGreaterThan(0);
    expect(result.audit.unsupported_knob_influence_ids).toContain("pboc_fed_policy_weight");
    expect(result.audit.sample_exclusion_reason).toContain("unsupported_knob_influence");
  });
});
