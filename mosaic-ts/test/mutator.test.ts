import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  parseResearchKnobsPrompt,
  type ResearchKnobs,
  renderResearchKnobsFence,
} from "../src/agents/helpers/research_knobs.js";
import {
  applyDomainKnobValueToProjection,
  buildDomainKnobValueRegistry,
  projectionValueForDomainCard,
  renderDomainKnobValueRegistry,
  replaceDomainKnobValueInProjection,
} from "../src/agents/prompts/domain_knob_registry.js";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import {
  buildPromptGovernanceValueRegistry,
  promptGovernanceValueRegistryPath,
  renderPromptGovernanceValueRegistry,
  updatePromptGovernanceRegistryFromProjection,
  validatePromptGovernanceValueRegistry,
} from "../src/agents/prompts/prompt_governance_registry.js";
import { buildRuntimeResearchKnobs } from "../src/agents/prompts/research_knobs_projection.js";
import { RUNTIME_AGENT_SPECS } from "../src/agents/prompts/runtime_agent_spec.js";
import type { KnobPatch } from "../src/autoresearch/mutator.js";
import {
  appendKnobMutationMetadataLog,
  applyKnobPatchesToDomainKnobRegistry,
  applyKnobPatchesToDomainKnobRegistryFile,
  applyKnobPatchesToGovernanceRegistry,
  applyKnobPatchesToGovernanceRegistryFile,
  applyKnobPatchesToProjection,
  applyKnobPatchesToPromptPair,
  assertPromptInvariants,
  assertPromptPairInvariants,
  assignDomainEvaluationAttemptIndex,
  buildKnobMutationMetadata,
  buildKnobTargetRegistry,
  type KnobMutation,
  KnobMutationSchema,
  MAX_LENGTH_DELTA,
  mutate,
  mutateResearchKnobs,
  PROMPT_CONTRACT_REQUIRED_SECTION_CATEGORIES,
  PromptInvariantError,
  validateKnobMutation,
} from "../src/autoresearch/mutator.js";
import type { BridgeApi } from "../src/bridge/types.js";

const BASE_PROMPT = `# volatility

## Role boundary
agent id volatility; layer macro; downstream consumer daily-cycle; no portfolio decision outside role.

## Required inputs/tools
Required tools: get_rke_research_context and current data tools. If missing tool or tool unavailable, fallback to conservative output and confidence cap applies.

## RKE prior policy
get_rke_research_context is a redacted research prior, not current data, cannot replace current data, and cannot directly create trades. no trade without current data confirmation.

## Workflow
Collect evidence, handle contradiction, confirm current data, reason in role, emit structured JSON.

## Output schema
Exact fields: regime_filter, confidence.

\`\`\`json
{ "agent": "volatility", "regime_filter": "x", "confidence": 0 }
\`\`\`

## Audit and footprint contract
Fields carry claim type, target, confidence, current-data confirmation, stale prior, contradictory prior, RKE context hash, ranking_policy_id, retrieval_rank, priority_bucket, truncation audit.

## Privacy boundary
Never output report prose, source spans, prompt body, local paths, URLs, reviewer text, or licensed metadata.

## Confidence policy
High confidence needs current data and two evidence families; fallback data caps confidence.

## Refusal and no-action behavior
If required data is unavailable, emit conservative no-action output inside schema.

## Autoresearch evolution contract
Mutable: thresholds and wording. Immutable: role boundary, output schema, required tools, current-data gate, rke-prior policy, privacy boundary, audit/footprint contract, shadow/promotion safety policy.
`;
const ZH = `${BASE_PROMPT}\n中文说明：做点事。\n`;
const EN = `${BASE_PROMPT}\nEnglish note: do stuff.\n`;
const ZH_LOCALIZED = `# volatility

## 角色边界
agent id volatility；layer macro；只在本角色内判断，不越权做组合决策。

## 必需输入与工具
必需工具：get_rke_research_context 和当前数据工具。若工具缺失或工具不可用，使用保守输出并应用置信度上限。

## RKE 先验策略
get_rke_research_context 是脱敏研究先验，不是当前数据，不能替代当前数据，不能直接生成交易。没有当前数据确认就不交易。

## 工作流程
收集证据，处理矛盾，确认当前数据，在角色边界内推理，输出结构化 JSON。

## 输出 schema
字段必须保持：regime_filter, confidence。

\`\`\`json
{ "agent": "volatility", "regime_filter": "x", "confidence": 0 }
\`\`\`

## 审计/足迹契约
字段承载 claim type、target、confidence、current-data confirmation、stale prior、contradictory prior、RKE context hash、ranking_policy_id、retrieval_rank、priority_bucket、truncation audit。

## 隐私边界
不得输出 report prose、source spans、prompt body、local paths、URLs、reviewer text 或 licensed metadata。

## 置信度策略
高置信度需要当前数据和两个证据族；fallback data caps confidence。

## 拒绝与 no-action
若必需数据不可用，在 schema 内输出保守 no-action。

## Autoresearch 演化契约
可变：阈值和措辞。不可变：角色边界、输出 schema、必需工具、当前数据门槛、RKE 先验策略、隐私边界、审计/足迹契约、shadow/promotion 安全策略。
`;

function knobsFixture(): ResearchKnobs {
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
        id: "policy_stance_1w",
        target_variable: "central_bank_stance",
        horizon: "1w",
        allowed_outputs: ["tightening", "neutral", "easing"],
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
    lookbacks: {},
    thresholds: {},
    confidence_caps: {
      missing_current_data: {
        cap: 0.55,
        trigger: "missing_required_evidence",
        enforcement: "code",
        required_evidence: ["pboc_liquidity"],
      },
    },
    tie_breaks: [],
    mutation_targets: [
      {
        path: "/rule_packs/*/rules/*/confidence_policy/missing_current_data/cap",
        type: "number",
        min: 0.25,
        max: 0.6,
        step: 0.05,
      },
      {
        path: "/rule_packs/*/rules/*/learnable_parameters/*/value",
        type: "number",
        min: 0,
        max: 1,
        step: 0.05,
      },
    ],
  };
}

function knobMutation(overrides: Partial<KnobMutation> = {}): KnobMutation {
  return {
    prediction_target: "policy_stance_1w",
    evaluation_metric: "confidence_calibration_error",
    horizon: "5d",
    rollback_condition: {
      metric: "confidence_calibration_error",
      worse_by: 0.03,
      unit: "ratio",
    },
    knob_patches: [
      {
        path: "/rule_packs/macro.central_bank.runtime.v1/rules/macro.central_bank.soft.001/confidence_policy/missing_current_data/cap",
        old_value: 0.55,
        new_value: 0.45,
        rationale: "Recent missing-data cases were overconfident.",
        expected_effect: "Lower confidence when current data is missing.",
      },
    ],
    renormalization: [],
    risk: "May lower recall in fast policy turns.",
    ...overrides,
  };
}

function knobsFencePrompt(body: string): string {
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
    - path: /rule_packs/*/rules/*/confidence_policy/missing_current_data/cap
      type: number
      min: 0.25
      max: 0.6
      step: 0.05
\`\`\`

${body}`;
}

function firstKnobPatch(): KnobPatch {
  return knobMutation().knob_patches[0] as KnobPatch;
}

// ── assertPromptInvariants ────────────────────────────────────────────────

describe("assertPromptInvariants", () => {
  it("accepts a focused valid edit", () => {
    const rewritten = ZH.replace("做点事", "做点更精确的事");
    expect(() => assertPromptInvariants(ZH, rewritten)).not.toThrow();
  });

  it("accepts localized Chinese contract sections", () => {
    const rewritten = ZH_LOCALIZED.replace("保守输出", "更保守的输出");
    expect(() => assertPromptInvariants(ZH_LOCALIZED, rewritten)).not.toThrow();
    expect(() => assertPromptPairInvariants(ZH_LOCALIZED, EN)).not.toThrow();
  });

  it("rejects a dropped section", () => {
    const rewritten = ZH.replace("## Output schema", "## Other schema");
    expect(() => assertPromptInvariants(ZH, rewritten)).toThrow(PromptInvariantError);
  });

  it("rejects a renamed schema field", () => {
    const rewritten = ZH.replace('"regime_filter"', '"regime"');
    expect(() => assertPromptInvariants(ZH, rewritten)).toThrow(/schema field/);
  });

  it("rejects an over-long rewrite", () => {
    const rewritten = ZH + "x".repeat(Math.ceil(ZH.length * (MAX_LENGTH_DELTA + 0.2)));
    expect(() => assertPromptInvariants(ZH, rewritten)).toThrow(/length/);
  });

  it("rejects a no-op", () => {
    expect(() => assertPromptInvariants(ZH, ZH)).toThrow(/no-op/);
  });

  it("rejects weakened RKE prior policy even when schema and workflow remain", () => {
    const rewritten = `${ZH}\nRKE prior is current data.`;
    expect(() => assertPromptInvariants(ZH, rewritten)).toThrow(/RKE prior/);
  });

  it("rejects removed privacy and no-action guardrails", () => {
    expect(() => assertPromptInvariants(ZH, ZH.replace("report prose", "research text"))).toThrow(
      /privacy/,
    );
    expect(() => assertPromptInvariants(ZH, ZH.replace("no-action", "active-action"))).toThrow(
      /refusal_no_action|no-action/,
    );
  });

  it("accepts mutable threshold wording while preserving immutable guardrails", () => {
    const rewritten = ZH.replace(
      "fallback data caps confidence.",
      "fallback data caps confidence at 0.5.",
    );
    expect(() => assertPromptInvariants(ZH, rewritten)).not.toThrow();
  });

  it("rejects bilingual section drift", () => {
    expect(() => assertPromptPairInvariants(ZH, EN.replace("## Workflow", "## Steps"))).toThrow(
      /desynchronized/,
    );
  });

  it("keeps TS required section names synchronized with E0.6 categories", () => {
    expect(PROMPT_CONTRACT_REQUIRED_SECTION_CATEGORIES).toEqual([
      "role_boundary",
      "required_inputs_tools",
      "rke_prior_policy",
      "workflow",
      "output_schema",
      "audit_footprint_contract",
      "privacy_boundary",
      "confidence_policy",
      "refusal_no_action",
      "autoresearch_evolution_contract",
    ]);
  });
});

describe("knob mutation validation", () => {
  it("rejects negative rollback deterioration thresholds", () => {
    expect(
      KnobMutationSchema.safeParse(
        knobMutation({
          rollback_condition: {
            metric: "confidence_calibration_error",
            worse_by: -0.01,
            unit: "ratio",
          },
        }),
      ).success,
    ).toBe(false);
  });

  it("accepts and applies an authorized confidence cap patch", () => {
    const knobs = knobsFixture();
    const mutation = knobMutation();

    expect(validateKnobMutation(knobs, mutation)).toEqual({ accepted: true, reasons: [] });

    const next = applyKnobPatchesToProjection(knobs, mutation);

    expect(next.confidence_caps.missing_current_data?.cap).toBe(0.45);
    expect(knobs.confidence_caps.missing_current_data?.cap).toBe(0.55);
  });

  it("rejects stale old_value, invalid step, and no-op patches", () => {
    const knobs = knobsFixture();

    expect(
      validateKnobMutation(
        knobs,
        knobMutation({ knob_patches: [{ ...firstKnobPatch(), old_value: 0.5 }] }),
      ).reasons,
    ).toContain(
      "/rule_packs/macro.central_bank.runtime.v1/rules/macro.central_bank.soft.001/confidence_policy/missing_current_data/cap: old_value does not match current knobs",
    );
    expect(
      validateKnobMutation(
        knobs,
        knobMutation({ knob_patches: [{ ...firstKnobPatch(), new_value: 0.47 }] }),
      ).reasons,
    ).toContain(
      "/rule_packs/*/rules/*/confidence_policy/missing_current_data/cap: value is not aligned to step",
    );
    expect(
      validateKnobMutation(
        knobs,
        knobMutation({ knob_patches: [{ ...firstKnobPatch(), new_value: 0.55 }] }),
      ).reasons,
    ).toContain(
      "/rule_packs/macro.central_bank.runtime.v1/rules/macro.central_bank.soft.001/confidence_policy/missing_current_data/cap: no-op patch",
    );
  });

  it("rejects integer patches outside range or step", () => {
    const execSpec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "autonomous_execution");
    expect(execSpec).toBeDefined();
    if (!execSpec) return;
    const knobs = buildRuntimeResearchKnobs(execSpec);
    const target = knobs.mutation_targets.find((item) =>
      item.path.endsWith("/learnable_parameters/max_order_split_count/value"),
    );
    expect(target).toBeDefined();
    if (!target) return;

    expect(
      validateKnobMutation(
        knobs,
        knobMutation({
          prediction_target: "execution_quality_5d",
          evaluation_metric: "turnover_adjusted_slippage",
          horizon: "5d",
          rollback_condition: {
            metric: "turnover_adjusted_slippage",
            worse_by: 0.001,
            unit: "ratio",
          },
          knob_patches: [
            {
              path: target.path,
              old_value: 5,
              new_value: 31,
              rationale: "Too many order splits should be rejected.",
              expected_effect: "No effect.",
            },
          ],
        }),
      ).reasons,
    ).toContain(`${target.path}: above max`);
  });

  it("rejects evidence weight patches against report-source reliability paths", () => {
    const knobs = knobsFixture();
    const mutation = knobMutation({
      knob_patches: [
        {
          path: "/research_weighting/source_profiles/AUTH-001/weight_policy",
          old_value: { weight_multiplier: 1, bucket: "neutral" },
          new_value: { weight_multiplier: 1.2, bucket: "positive" },
          rationale: "Wrong target space.",
          expected_effect: "Should be rejected.",
        },
      ],
    });

    expect(validateKnobMutation(knobs, mutation).reasons).toContain(
      "evidence weight patch must not target report-source reliability paths",
    );
  });

  it("checks evidence-channel old_value against the current projection", () => {
    const knobs = knobsFixture();
    const mutation = knobMutation({
      knob_patches: [
        {
          path: "/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/pboc_liquidity_weight/value",
          old_value: 0.5,
          new_value: 0.65,
          rationale: "Stale channel write.",
          expected_effect: "Should be rejected before registry write.",
        },
      ],
    });

    expect(validateKnobMutation(knobs, mutation).reasons).toContain(
      "/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/pboc_liquidity_weight/value: old_value does not match current knobs",
    );
  });

  it("rejects generic targets with unsupported evaluation metrics", () => {
    const knobs = knobsFixture();

    expect(
      validateKnobMutation(
        knobs,
        knobMutation({
          evaluation_metric: "portfolio_construction_quality_20d",
          rollback_condition: {
            metric: "portfolio_construction_quality_20d",
            worse_by: 0.02,
            unit: "ratio",
          },
        }),
      ).reasons.join("\n"),
    ).toContain("evaluation_metric portfolio_construction_quality_20d is not allowed");
  });

  it("builds a unified knob target registry with write-back sources", () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "central_bank");
    expect(spec).toBeDefined();
    if (!spec) return;
    const knobs = buildRuntimeResearchKnobs(spec);
    const registry = buildKnobTargetRegistry(knobs);

    expect(registry).toHaveLength(knobs.mutation_targets.length);
    expect(registry).toContainEqual(
      expect.objectContaining({
        path: expect.stringContaining("/confidence_policy/missing_current_data/cap"),
        category: "generic",
        write_back_source: "prompt_ir_governance_registry",
        write_back_repo_id: "MOSAIC-Prompts",
        write_back_path: "registry/prompt_governance/cohort_default/central_bank.json",
        write_back_json_pointer: expect.stringContaining("/values_by_path/~1rule_packs~1"),
        evaluation_metrics: expect.arrayContaining(["confidence_calibration_error"]),
      }),
    );
    expect(registry).toContainEqual(
      expect.objectContaining({
        path: expect.stringContaining("/learnable_parameters/pboc_fed_policy_weight/value"),
        category: "domain",
        write_back_source: "domain_knob_value_registry",
        write_back_path: "registry/domain_knobs/cohort_default/central_bank.json",
        domain_card_id: "pboc_fed_policy_weight",
        evaluation_metrics: expect.arrayContaining([
          "macro_signal_accuracy_5d",
          "confidence_calibration_error",
        ]),
        rollback_metrics: expect.arrayContaining([
          "macro_signal_accuracy_5d",
          "confidence_calibration_error",
        ]),
      }),
    );
    for (const target of knobs.mutation_targets) {
      expect(registry.filter((entry) => entry.path === target.path)).toHaveLength(1);
    }
  });

  it("writes generic projection changes back to the physical governance registry", () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "central_bank");
    expect(spec).toBeDefined();
    if (!spec) return;
    const registry = buildPromptGovernanceValueRegistry(spec, "cohort_default");
    const baseKnobs = buildRuntimeResearchKnobs(spec, { governanceRegistry: registry });
    const mutation = knobMutation({
      prediction_target: baseKnobs.prediction_targets[0]?.id ?? "macro.central_bank.soft.001",
      knob_patches: [
        {
          path: baseKnobs.mutation_targets.find((target) =>
            target.path.includes("/confidence_policy/missing_current_data/cap"),
          )?.path as string,
          old_value: 0.55,
          new_value: 0.5,
          rationale: "Tighten missing-data calibration.",
          expected_effect: "Reduce unsupported high-confidence outputs.",
        },
      ],
    });
    const newKnobs = applyKnobPatchesToProjection(baseKnobs, mutation);

    const result = updatePromptGovernanceRegistryFromProjection({
      registry,
      spec,
      baseKnobs,
      newKnobs,
      mutation,
      mutationId: "KM-generic-1",
    });

    expect(result.registry.last_mutation_id).toBe("KM-generic-1");
    expect(result.registry.values_by_path[mutation.knob_patches[0]?.path ?? ""]).toBe(0.5);
    expect(validatePromptGovernanceValueRegistry(spec, result.registry)).toEqual([]);
    const metadata = buildKnobMutationMetadata({
      mutationId: "KM-generic-1",
      agent: "central_bank",
      cohort: "cohort_default",
      baseKnobs,
      newKnobs,
      mutation,
      decision: "applied",
      createdAt: "2026-07-08T00:00:00.000Z",
    });
    expect(metadata.mutation_kind).toBe("generic_knob");
    expect(metadata.generic_target_paths).toEqual([mutation.knob_patches[0]?.path]);
    expect(metadata.owner_agent).toBe("macro.central_bank");
    expect(metadata.evaluation_policy.require_uncertainty_bound).toBe(true);
    expect(metadata.evaluation_policy.preregistration_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
  });

  it("applies concrete learnable-parameter patches to a governance registry payload", () => {
    const knobs = knobsFixture();
    const registry = {
      rule_packs: {
        "macro.central_bank.liquidity.v1": {
          rules: {
            "macro.central_bank.soft.001": {
              learnable_parameters: {
                pboc_liquidity_weight: {
                  value: 1,
                },
              },
            },
          },
        },
      },
    };
    const mutation = knobMutation({
      knob_patches: [
        {
          path: "/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/pboc_liquidity_weight/value",
          old_value: 1,
          new_value: 0.65,
          rationale: "PBOC channel has calibrated better in the latest window.",
          expected_effect: "Increase PBOC evidence-channel allocation raw value.",
        },
      ],
      renormalization: [
        {
          group: "evidence_weights",
          raw_values: { pboc_liquidity: 0.65 },
        },
      ],
    });

    const result = applyKnobPatchesToGovernanceRegistry(registry, knobs, mutation);

    expect(
      result.registry.rule_packs["macro.central_bank.liquidity.v1"].rules[
        "macro.central_bank.soft.001"
      ].learnable_parameters.pboc_liquidity_weight.value,
    ).toBe(0.65);
    expect(
      registry.rule_packs["macro.central_bank.liquidity.v1"].rules["macro.central_bank.soft.001"]
        .learnable_parameters.pboc_liquidity_weight.value,
    ).toBe(1);
    expect(result.changed_paths).toEqual([
      "/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/pboc_liquidity_weight/value",
    ]);
  });

  it("applies projection patches to both prompt fences while preserving bodies", () => {
    const result = applyKnobPatchesToPromptPair(
      knobsFencePrompt("# zh body"),
      knobsFencePrompt("# en body"),
      knobMutation(),
    );

    expect(result.knobs.confidence_caps.missing_current_data?.cap).toBe(0.45);
    expect(result.zh_prompt).toContain("cap: 0.45");
    expect(result.en_prompt).toContain("cap: 0.45");
    expect(result.zh_prompt).toContain("# zh body");
    expect(result.en_prompt).toContain("# en body");
    expect(result.zh_prompt).toContain("```research-knobs");
    expect(result.en_prompt).toContain("```research-knobs");
  });

  it("renormalizes projection evidence weights after learnable-parameter patches", () => {
    const knobs = knobsFixture();
    knobs.evidence_registry.fed_policy = {
      tool: "get_fed_policy",
      metric: "fed_policy_path",
      current_data: true,
      primary: false,
    };
    knobs.evidence_weights = {
      pboc_liquidity: 0.5,
      fed_policy: 0.5,
    };
    const next = applyKnobPatchesToProjection(
      knobs,
      knobMutation({
        knob_patches: [
          {
            path: "/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/pboc_liquidity_weight/value",
            old_value: 0.5,
            new_value: 0.75,
            rationale: "PBOC channel has calibrated better in recent evaluations.",
            expected_effect: "Increase normalized PBOC evidence-channel allocation.",
          },
        ],
        renormalization: [
          {
            group: "evidence_weights",
            raw_values: { pboc_liquidity: 0.75, fed_policy: 0.25 },
          },
        ],
      }),
    );

    expect(next.evidence_weights.pboc_liquidity).toBe(0.75);
    expect(next.evidence_weights.fed_policy).toBe(0.25);
    expect(knobs.evidence_weights.pboc_liquidity).toBe(0.5);
  });

  it("applies catalog-governed domain knob patches to projection buckets", () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "central_bank");
    expect(spec).toBeDefined();
    if (!spec) return;
    const knobs = buildRuntimeResearchKnobs(spec);
    const target = knobs.mutation_targets.find((item) =>
      item.path.endsWith("/learnable_parameters/pboc_fed_policy_weight/value"),
    );
    expect(target).toBeDefined();
    if (!target) return;

    const next = applyKnobPatchesToProjection(
      knobs,
      knobMutation({
        prediction_target: "macro.central_bank.pboc_fed_policy_weight.5d",
        evaluation_metric: "macro_signal_accuracy_5d",
        horizon: "5d",
        rollback_condition: {
          metric: "macro_signal_accuracy_5d",
          worse_by: 0.02,
          unit: "ratio",
        },
        knob_patches: [
          {
            path: target.path,
            old_value: 0.2,
            new_value: 0.35,
            rationale: "PBOC/Fed policy split has become more predictive.",
            expected_effect: "Increase the policy-divergence domain threshold weight.",
          },
        ],
      }),
    );

    expect(next.thresholds.pboc_fed_policy_weight).toBe(0.35);
    expect(knobs.thresholds.pboc_fed_policy_weight).toBe(0.2);
  });

  it("projects catalog-governed domain knobs into every v1 bucket", () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "central_bank");
    expect(spec).toBeDefined();
    if (!spec) return;
    const knobs = buildRuntimeResearchKnobs(spec);

    applyDomainKnobValueToProjection(
      knobs,
      { id: "custom_window_days", projection_bucket: "lookbacks" },
      12,
    );
    applyDomainKnobValueToProjection(
      knobs,
      { id: "custom_threshold", projection_bucket: "thresholds" },
      0.25,
    );
    applyDomainKnobValueToProjection(
      knobs,
      { id: "pboc_liquidity", projection_bucket: "evidence_weights" },
      0.42,
    );
    applyDomainKnobValueToProjection(
      knobs,
      { id: "missing_current_data", projection_bucket: "confidence_caps" },
      0.45,
    );
    applyDomainKnobValueToProjection(
      knobs,
      { id: "risk_priority", projection_bucket: "tie_breaks" },
      "risk_priority",
    );
    replaceDomainKnobValueInProjection(
      knobs,
      { id: "risk_priority", projection_bucket: "tie_breaks" },
      "risk_priority",
      "liquidity_priority",
    );

    expect(
      projectionValueForDomainCard(knobs, {
        id: "custom_window_days",
        projection_bucket: "lookbacks",
      }),
    ).toBe(12);
    expect(
      projectionValueForDomainCard(knobs, {
        id: "custom_threshold",
        projection_bucket: "thresholds",
      }),
    ).toBe(0.25);
    expect(
      projectionValueForDomainCard(knobs, {
        id: "pboc_liquidity",
        projection_bucket: "evidence_weights",
      }),
    ).toBe(0.42);
    expect(
      projectionValueForDomainCard(knobs, {
        id: "missing_current_data",
        projection_bucket: "confidence_caps",
      }),
    ).toBe(0.45);
    expect(
      projectionValueForDomainCard(knobs, {
        id: "risk_priority",
        projection_bucket: "tie_breaks",
        default: "liquidity_priority",
      }),
    ).toBe("liquidity_priority");
    expect(knobs.tie_breaks).not.toContain("risk_priority");
  });

  it("writes catalog-governed domain knob patches through the value registry", () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "central_bank");
    expect(spec).toBeDefined();
    if (!spec) return;
    const registry = buildDomainKnobValueRegistry(spec, "cohort_default");
    const knobs = buildRuntimeResearchKnobs(spec, { domainRegistry: registry });
    const target = knobs.mutation_targets.find((item) =>
      item.path.endsWith("/learnable_parameters/pboc_fed_policy_weight/value"),
    );
    expect(target).toBeDefined();
    if (!target) return;

    const result = applyKnobPatchesToDomainKnobRegistry(
      registry,
      knobs,
      knobMutation({
        prediction_target: "macro.central_bank.pboc_fed_policy_weight.5d",
        evaluation_metric: "macro_signal_accuracy_5d",
        horizon: "5d",
        rollback_condition: {
          metric: "macro_signal_accuracy_5d",
          worse_by: 0.02,
          unit: "ratio",
        },
        knob_patches: [
          {
            path: target.path,
            old_value: 0.2,
            new_value: 0.35,
            rationale: "PBOC/Fed policy split has become more predictive.",
            expected_effect: "Persist the domain value before projection regeneration.",
          },
        ],
      }),
      { mutationId: "KM-domain-1" },
    );
    const regenerated = buildRuntimeResearchKnobs(spec, { domainRegistry: result.registry });

    expect(result.changed_paths).toEqual([target.path]);
    expect(result.registry.values_by_path[target.path]).toBe(0.35);
    expect(result.registry.last_mutation_id).toBe("KM-domain-1");
    expect(regenerated.thresholds.pboc_fed_policy_weight).toBe(0.35);
    expect(registry.values_by_path[target.path]).toBe(0.2);
  });

  it("renormalizes catalog-governed domain weight groups", () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "semiconductor");
    expect(spec).toBeDefined();
    if (!spec) return;
    const registry = buildDomainKnobValueRegistry(spec, "cohort_default");
    const knobs = buildRuntimeResearchKnobs(spec, { domainRegistry: registry });
    const target = knobs.mutation_targets.find((item) =>
      item.path.endsWith("/learnable_parameters/design_weight/value"),
    );
    expect(target).toBeDefined();
    if (!target) return;

    const mutation = knobMutation({
      prediction_target: "sector.semiconductor.design_weight.20d",
      evaluation_metric: "sector_rank_correlation_20d",
      horizon: "20d",
      rollback_condition: {
        metric: "sector_rank_correlation_20d",
        worse_by: 0.02,
        unit: "ratio",
      },
      knob_patches: [
        {
          path: target.path,
          old_value: 0.18,
          new_value: 0.28,
          rationale: "Design names recently explained more sector rank quality.",
          expected_effect: "Increase design share and renormalize peer weights.",
        },
      ],
    });
    const projected = applyKnobPatchesToProjection(knobs, mutation);
    const persisted = applyKnobPatchesToDomainKnobRegistry(registry, knobs, mutation);
    const projectedTotal =
      Number(projected.thresholds.design_weight) +
      Number(projected.thresholds.equipment_weight) +
      Number(projected.thresholds.foundry_weight) +
      Number(projected.thresholds.packaging_weight) +
      Number(projected.thresholds.materials_weight) +
      Number(projected.thresholds.ai_compute_weight);
    const persistedTotal = Object.entries(persisted.registry.values_by_path)
      .filter(([path]) =>
        [
          "design_weight",
          "equipment_weight",
          "foundry_weight",
          "packaging_weight",
          "materials_weight",
          "ai_compute_weight",
        ].some((id) => path.endsWith(`/learnable_parameters/${id}/value`)),
      )
      .reduce((sum, [, value]) => sum + Number(value), 0);

    expect(projectedTotal).toBeCloseTo(1, 10);
    expect(persistedTotal).toBeCloseTo(1, 10);
    expect(projected.thresholds.design_weight).toBeCloseTo(0.28 / 1.1, 10);
  });

  it("rejects domain knob patches that break cross-field invariants", () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "cio");
    expect(spec).toBeDefined();
    if (!spec) return;
    const knobs = buildRuntimeResearchKnobs(spec);
    const target = knobs.mutation_targets.find((item) =>
      item.path.endsWith("/learnable_parameters/min_confidence_to_hold/value"),
    );
    expect(target).toBeDefined();
    if (!target) return;

    expect(
      validateKnobMutation(
        knobs,
        knobMutation({
          prediction_target: "hold_exit_quality_20d",
          evaluation_metric: "max_drawdown_after_hold",
          horizon: "20d",
          rollback_condition: {
            metric: "max_drawdown_after_hold",
            worse_by: 0.02,
            unit: "ratio",
          },
          knob_patches: [
            {
              path: target.path,
              old_value: 0.5,
              new_value: 0.7,
              rationale: "Hold threshold cannot exceed the add threshold.",
              expected_effect: "Should be rejected because min_confidence_to_add remains 0.65.",
            },
          ],
        }),
      ).reasons,
    ).toContain("domain_cross_field_violation:cio_min_hold_gt_add");
  });

  it("repairs stale cross-field registry values when rebuilding domain registries", () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "cio");
    expect(spec).toBeDefined();
    if (!spec) return;
    const existing = buildDomainKnobValueRegistry(spec, "cohort_default");
    const addPath = Object.keys(existing.values_by_path).find((path) =>
      path.endsWith("/learnable_parameters/min_confidence_to_add/value"),
    );
    const holdConfidencePath = Object.keys(existing.values_by_path).find((path) =>
      path.endsWith("/learnable_parameters/min_confidence_to_hold/value"),
    );
    expect(addPath).toBeDefined();
    expect(holdConfidencePath).toBeDefined();
    if (!addPath || !holdConfidencePath) return;
    existing.values_by_path[addPath] = 0.55;
    existing.values_by_path[holdConfidencePath] = 0.7;

    const repaired = buildDomainKnobValueRegistry(spec, "cohort_default", { existing });

    expect(repaired.values_by_path[addPath]).toBe(0.65);
    expect(repaired.values_by_path[holdConfidencePath]).toBe(0.5);
  });

  it("preserves registry values only after a durable mutation id is present", () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "central_bank");
    expect(spec).toBeDefined();
    if (!spec) return;
    const baseline = buildDomainKnobValueRegistry(spec, "cohort_default");
    const path = Object.keys(baseline.values_by_path).find((item) =>
      item.endsWith("/learnable_parameters/policy_conflict_cap/value"),
    );
    expect(path).toBeDefined();
    if (!path) return;
    baseline.values_by_path[path] = 0.3;

    expect(
      buildDomainKnobValueRegistry(spec, "cohort_default", { existing: baseline }).values_by_path[
        path
      ],
    ).toBe(0.25);
    baseline.last_mutation_id = "KM-1";
    expect(
      buildDomainKnobValueRegistry(spec, "cohort_default", { existing: baseline }).values_by_path[
        path
      ],
    ).toBe(0.3);
  });

  it("rejects domain knob mutations with the wrong evaluation metric", () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "central_bank");
    expect(spec).toBeDefined();
    if (!spec) return;
    const knobs = buildRuntimeResearchKnobs(spec);
    const target = knobs.mutation_targets.find((item) =>
      item.path.endsWith("/learnable_parameters/pboc_fed_policy_weight/value"),
    );
    expect(target).toBeDefined();
    if (!target) return;

    expect(
      validateKnobMutation(
        knobs,
        knobMutation({
          prediction_target: "macro.central_bank.pboc_fed_policy_weight.5d",
          evaluation_metric: "portfolio_construction_quality_20d",
          rollback_condition: {
            metric: "portfolio_construction_quality_20d",
            worse_by: 0.02,
            unit: "ratio",
          },
          knob_patches: [
            {
              path: target.path,
              old_value: 0.2,
              new_value: 0.35,
              rationale: "Wrong metric for this domain card.",
              expected_effect: "Should be rejected.",
            },
          ],
        }),
      ).reasons.join("\n"),
    ).toContain(
      "evaluation_metric portfolio_construction_quality_20d is not allowed for domain card",
    );
  });

  it("allows domain knob mutations to choose registered secondary metrics", () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "central_bank");
    expect(spec).toBeDefined();
    if (!spec) return;
    const knobs = buildRuntimeResearchKnobs(spec);
    const target = knobs.mutation_targets.find((item) =>
      item.path.endsWith("/learnable_parameters/pboc_fed_policy_weight/value"),
    );
    expect(target).toBeDefined();
    if (!target) return;

    expect(
      validateKnobMutation(
        knobs,
        knobMutation({
          prediction_target: "macro.central_bank.pboc_fed_policy_weight.5d",
          evaluation_metric: "confidence_calibration_error",
          horizon: "5d",
          rollback_condition: {
            metric: "confidence_calibration_error",
            worse_by: 0.03,
            unit: "ratio",
          },
          knob_patches: [
            {
              path: target.path,
              old_value: 0.2,
              new_value: 0.35,
              rationale: "Use the card's registered calibration side metric.",
              expected_effect: "Improve confidence calibration for this domain parameter.",
            },
          ],
        }),
      ).accepted,
    ).toBe(true);
  });

  it("accepts position-aware and MiroFish domain knob metrics", () => {
    const croSpec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "cro");
    const cioSpec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "cio");
    expect(croSpec).toBeDefined();
    expect(cioSpec).toBeDefined();
    if (!croSpec || !cioSpec) return;
    const croKnobs = buildRuntimeResearchKnobs(croSpec);
    const cioKnobs = buildRuntimeResearchKnobs(cioSpec);
    const stopLoss = croKnobs.mutation_targets.find((item) =>
      item.path.endsWith("/learnable_parameters/stop_loss_pct/value"),
    );
    const mirofishOverride = cioKnobs.mutation_targets.find((item) =>
      item.path.endsWith("/learnable_parameters/mirofish_override_hurdle/value"),
    );
    expect(stopLoss).toBeDefined();
    expect(mirofishOverride).toBeDefined();
    if (!stopLoss || !mirofishOverride) return;

    expect(
      validateKnobMutation(
        croKnobs,
        knobMutation({
          prediction_target: "hold_exit_quality_20d",
          evaluation_metric: "max_drawdown_after_hold",
          horizon: "20d",
          knob_patches: [
            {
              path: stopLoss.path,
              old_value: -0.08,
              new_value: -0.06,
              rationale: "Stop-loss overrides have carried too much drawdown.",
              expected_effect: "Trigger review earlier on losing current positions.",
            },
          ],
          rollback_condition: {
            metric: "max_drawdown_after_hold",
            worse_by: 0.02,
            unit: "ratio",
          },
        }),
      ).accepted,
    ).toBe(true);
    expect(
      validateKnobMutation(
        cioKnobs,
        knobMutation({
          prediction_target: "override_quality_20d",
          evaluation_metric: "override_realized_risk",
          horizon: "20d",
          knob_patches: [
            {
              path: mirofishOverride.path,
              old_value: 0.75,
              new_value: 0.8,
              rationale: "Scenario-only overrides should require stronger agreement.",
              expected_effect: "Reduce realized risk from MiroFish-influenced overrides.",
            },
          ],
          rollback_condition: {
            metric: "override_realized_risk",
            worse_by: 0.02,
            unit: "ratio",
          },
        }),
      ).accepted,
    ).toBe(true);
  });

  it("writes domain knob registry files transactionally after validation", async () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "central_bank");
    expect(spec).toBeDefined();
    if (!spec) return;
    const dir = mkdtempSync(join(tmpdir(), "mosaic-domain-knob-registry-"));
    try {
      const registryPath = join(dir, "central_bank.json");
      const registry = buildDomainKnobValueRegistry(spec, "cohort_default");
      writeFileSync(registryPath, `${JSON.stringify(registry, null, 2)}\n`, "utf-8");
      const knobs = buildRuntimeResearchKnobs(spec, { domainRegistry: registry });
      const target = knobs.mutation_targets.find((item) =>
        item.path.endsWith("/learnable_parameters/pboc_fed_policy_weight/value"),
      );
      expect(target).toBeDefined();
      if (!target) return;

      await applyKnobPatchesToDomainKnobRegistryFile({
        registryPath,
        knobs,
        mutation: knobMutation({
          prediction_target: "macro.central_bank.pboc_fed_policy_weight.5d",
          evaluation_metric: "macro_signal_accuracy_5d",
          horizon: "5d",
          rollback_condition: {
            metric: "macro_signal_accuracy_5d",
            worse_by: 0.02,
            unit: "ratio",
          },
          knob_patches: [
            {
              path: target.path,
              old_value: 0.2,
              new_value: 0.35,
              rationale: "Persist domain knob registry update.",
              expected_effect: "Regenerated projection reads the updated domain registry value.",
            },
          ],
        }),
        mutationId: "KM-domain-file",
      });

      expect(JSON.parse(readFileSync(registryPath, "utf-8")).values_by_path[target.path]).toBe(
        0.35,
      );
      await expect(
        applyKnobPatchesToDomainKnobRegistryFile({
          registryPath,
          knobs,
          mutation: knobMutation({
            prediction_target: "macro.central_bank.pboc_fed_policy_weight.5d",
            evaluation_metric: "macro_signal_accuracy_5d",
            horizon: "5d",
            rollback_condition: {
              metric: "macro_signal_accuracy_5d",
              worse_by: 0.02,
              unit: "ratio",
            },
            knob_patches: [
              {
                path: target.path,
                old_value: 0.2,
                new_value: 0.4,
                rationale: "Stale domain write.",
                expected_effect: "Should be rejected.",
              },
            ],
          }),
        }),
      ).rejects.toThrow(/old_value does not match domain knob registry/);
      expect(JSON.parse(readFileSync(registryPath, "utf-8")).values_by_path[target.path]).toBe(
        0.35,
      );
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("rejects governance registry writes when old_value is stale", () => {
    const knobs = knobsFixture();
    const registry = {
      rule_packs: {
        "macro.central_bank.liquidity.v1": {
          rules: {
            "macro.central_bank.soft.001": {
              learnable_parameters: {
                pboc_liquidity_weight: {
                  value: 0.55,
                },
              },
            },
          },
        },
      },
    };
    const mutation = knobMutation({
      knob_patches: [
        {
          path: "/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/pboc_liquidity_weight/value",
          old_value: 1,
          new_value: 0.65,
          rationale: "Stale mutation.",
          expected_effect: "Should be rejected.",
        },
      ],
    });

    expect(() => applyKnobPatchesToGovernanceRegistry(registry, knobs, mutation)).toThrow(
      /old_value does not match governance registry/,
    );
  });

  it("writes governance registry files transactionally after validation", async () => {
    const dir = mkdtempSync(join(tmpdir(), "mosaic-governance-registry-"));
    try {
      const registryPath = join(dir, "registry.json");
      writeFileSync(
        registryPath,
        JSON.stringify(
          {
            rule_packs: {
              "macro.central_bank.liquidity.v1": {
                rules: {
                  "macro.central_bank.soft.001": {
                    learnable_parameters: {
                      pboc_liquidity_weight: { value: 1 },
                    },
                  },
                },
              },
            },
          },
          null,
          2,
        ),
        "utf-8",
      );

      await applyKnobPatchesToGovernanceRegistryFile({
        registryPath,
        knobs: knobsFixture(),
        mutation: knobMutation({
          knob_patches: [
            {
              path: "/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/pboc_liquidity_weight/value",
              old_value: 1,
              new_value: 0.65,
              rationale: "Increase PBOC raw evidence weight.",
              expected_effect: "Raise normalized PBOC evidence channel after projection.",
            },
          ],
        }),
      });

      expect(
        JSON.parse(readFileSync(registryPath, "utf-8")).rule_packs[
          "macro.central_bank.liquidity.v1"
        ].rules["macro.central_bank.soft.001"].learnable_parameters.pboc_liquidity_weight.value,
      ).toBe(0.65);

      await expect(
        applyKnobPatchesToGovernanceRegistryFile({
          registryPath,
          knobs: knobsFixture(),
          mutation: knobMutation({
            knob_patches: [
              {
                path: "/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/pboc_liquidity_weight/value",
                old_value: 1,
                new_value: 0.7,
                rationale: "Stale update.",
                expected_effect: "Should be rejected.",
              },
            ],
          }),
        }),
      ).rejects.toThrow(/old_value does not match/);
      expect(
        JSON.parse(readFileSync(registryPath, "utf-8")).rule_packs[
          "macro.central_bank.liquidity.v1"
        ].rules["macro.central_bank.soft.001"].learnable_parameters.pboc_liquidity_weight.value,
      ).toBe(0.65);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("builds append-only knob mutation metadata without prompt bodies", async () => {
    const dir = mkdtempSync(join(tmpdir(), "mosaic-knob-mutation-log-"));
    try {
      const baseKnobs = knobsFixture();
      const mutation = knobMutation();
      const newKnobs = applyKnobPatchesToProjection(baseKnobs, mutation);
      const metadata = buildKnobMutationMetadata({
        mutationId: "KM-1",
        agent: "central_bank",
        cohort: "cohort_default",
        baseKnobs,
        newKnobs,
        mutation,
        decision: "dry_run",
        createdAt: "2026-07-08T00:00:00.000Z",
      });

      expect(metadata.base_knobs_sha256).toMatch(/^sha256:/);
      expect(metadata.new_knobs_sha256).toMatch(/^sha256:/);
      expect(metadata.base_knobs_sha256).not.toBe(metadata.new_knobs_sha256);
      expect(metadata.changed_paths).toEqual([mutation.knob_patches[0]?.path]);
      expect(JSON.stringify(metadata)).not.toContain("Current zh prompt");

      const logPath = join(dir, "mutation_patches", "knob_mutations.jsonl");
      await appendKnobMutationMetadataLog({ logPath, metadata });
      await appendKnobMutationMetadataLog({ logPath, metadata });
      const rows = readFileSync(logPath, "utf-8")
        .trim()
        .split("\n")
        .map((line) => JSON.parse(line) as Record<string, unknown>);
      expect(rows).toHaveLength(1);
      const row = rows[0];
      expect(row).toBeDefined();
      expect(row?.mutation_id).toBe("KM-1");
      expect(row?.decision).toBe("dry_run");
      await expect(
        appendKnobMutationMetadataLog({
          logPath,
          metadata: { ...metadata, risk: "conflicting retry" },
        }),
      ).rejects.toThrow(/metadata conflict/);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("preregisters purged splits and counts attempts within an experiment family", async () => {
    const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "central_bank");
    expect(spec).toBeDefined();
    if (!spec) return;
    const baseKnobs = buildRuntimeResearchKnobs(spec);
    const target = baseKnobs.mutation_targets.find((item) =>
      item.path.endsWith("/learnable_parameters/pboc_fed_policy_weight/value"),
    );
    expect(target).toBeDefined();
    if (!target) return;
    const mutation = knobMutation({
      prediction_target: "macro.central_bank.pboc_fed_policy_weight.5d",
      evaluation_metric: "confidence_calibration_error",
      horizon: "5d",
      rollback_condition: {
        metric: "confidence_calibration_error",
        worse_by: 0.03,
        unit: "ratio",
      },
      knob_patches: [
        {
          path: target.path,
          old_value: 0.2,
          new_value: 0.35,
          rationale: "Evaluate a bounded policy-weight change.",
          expected_effect: "Improve calibrated policy regime calls.",
        },
      ],
    });
    expect(validateKnobMutation(baseKnobs, mutation).accepted).toBe(true);
    const newKnobs = applyKnobPatchesToProjection(baseKnobs, mutation);
    const metadata = buildKnobMutationMetadata({
      mutationId: "KM-domain-preregistered",
      experimentId: "EXP-domain-preregistered",
      agent: "central_bank",
      cohort: "cohort_default",
      baseKnobs,
      newKnobs,
      mutation,
      decision: "applied",
      createdAt: "2026-07-10T00:00:00.000Z",
      experimentFamilySize: 20,
    });

    const preregistration = metadata.evaluation_policy.preregistration;
    expect(preregistration).toMatchObject({
      schema_version: "domain_evaluation_preregistration_v1",
      experiment_id: "EXP-domain-preregistered",
      calendar_id: "cn_a_share",
      primary_metric: "confidence_calibration_error",
      common_support_required: true,
      multiple_testing: {
        method: "bonferroni",
        attempt_index: 1,
        family_size: 20,
        adjusted_alpha: 0.0025,
      },
    });
    expect(preregistration?.split_policy.holdout.reuse_budget).toBe(1);
    expect(preregistration?.secondary_guardrails.map((item) => item.metric_id)).toEqual(
      expect.arrayContaining(["fallback_rate", "missing_rate"]),
    );
    expect(metadata.evaluation_policy.preregistration_hash).toMatch(/^sha256:[0-9a-f]{64}$/);

    const dir = mkdtempSync(join(tmpdir(), "mosaic-domain-attempts-"));
    try {
      const logPath = join(dir, "knob_mutations.jsonl");
      const first = await assignDomainEvaluationAttemptIndex({ logPath, metadata });
      await appendKnobMutationMetadataLog({ logPath, metadata: first });
      const secondCandidate = buildKnobMutationMetadata({
        mutationId: "KM-domain-preregistered-2",
        experimentId: "EXP-domain-preregistered-2",
        agent: "central_bank",
        cohort: "cohort_default",
        baseKnobs,
        newKnobs,
        mutation,
        decision: "applied",
        createdAt: "2026-07-11T00:00:00.000Z",
        experimentFamilySize: 20,
      });
      const second = await assignDomainEvaluationAttemptIndex({
        logPath,
        metadata: secondCandidate,
      });
      expect(second.evaluation_policy.preregistration?.multiple_testing.attempt_index).toBe(2);
      expect(second.evaluation_policy.preregistration?.multiple_testing.adjusted_alpha).toBe(
        0.0025,
      );
      await appendKnobMutationMetadataLog({ logPath, metadata: second });
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

// ── mutate ────────────────────────────────────────────────────────────────

interface FakeRoot {
  root: string;
  cleanup: () => void;
}

function makeRoot(): FakeRoot {
  const root = mkdtempSync(join(tmpdir(), "mosaic-mutator-test-"));
  const dir = join(root, "cohort_default", "macro");
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "volatility.zh.md"), ZH, "utf-8");
  writeFileSync(join(dir, "volatility.en.md"), EN, "utf-8");
  return { root, cleanup: () => rmSync(root, { recursive: true, force: true }) };
}

function makeKnobsRoot(): FakeRoot {
  const repoRoot = mkdtempSync(join(tmpdir(), "mosaic-knob-mutator-test-"));
  const root = join(repoRoot, "prompts", "mosaic");
  const dir = join(root, "cohort_default", "macro");
  mkdirSync(dir, { recursive: true });
  const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "volatility");
  if (!spec) throw new Error("volatility runtime spec missing");
  const knobs = buildRuntimeResearchKnobs(spec);
  writeFileSync(
    join(dir, "volatility.zh.md"),
    `${renderResearchKnobsFence(knobs)}\n\n# zh body`,
    "utf-8",
  );
  writeFileSync(
    join(dir, "volatility.en.md"),
    `${renderResearchKnobsFence(knobs)}\n\n# en body`,
    "utf-8",
  );
  const governancePath = promptGovernanceValueRegistryPath({
    privatePromptsRoot: root,
    cohort: "cohort_default",
    agent: spec.agent,
  });
  mkdirSync(join(repoRoot, "registry", "prompt_governance", "cohort_default"), {
    recursive: true,
  });
  writeFileSync(
    governancePath,
    renderPromptGovernanceValueRegistry(buildPromptGovernanceValueRegistry(spec, "cohort_default")),
    "utf-8",
  );
  return { root, cleanup: () => rmSync(repoRoot, { recursive: true, force: true }) };
}

function makeLegacyDecisionRoot(): FakeRoot {
  const repoRoot = mkdtempSync(join(tmpdir(), "mosaic-legacy-knob-mutator-test-"));
  const root = join(repoRoot, "prompts", "mosaic");
  const dir = join(root, "cohort_default", "decision");
  mkdirSync(dir, { recursive: true });
  const spec = RUNTIME_AGENT_SPECS.find((item) => item.agent === "cio");
  if (!spec) throw new Error("cio runtime spec missing");
  const canonicalFence = renderResearchKnobsFence(buildRuntimeResearchKnobs(spec));
  const driftedFence = canonicalFence.replace("stale_thesis_days: 20", "stale_thesis_days: 25");
  if (driftedFence === canonicalFence) throw new Error("cio drift fixture target missing");
  writeFileSync(join(dir, "cio.zh.md"), `${driftedFence}\n\n# zh cio body\n`, "utf-8");
  writeFileSync(join(dir, "cio.en.md"), `${driftedFence}\n\n# en cio body\n`, "utf-8");
  const registryPath = join(repoRoot, "registry", "domain_knobs", "cohort_default", "cio.json");
  mkdirSync(join(repoRoot, "registry", "domain_knobs", "cohort_default"), { recursive: true });
  writeFileSync(
    registryPath,
    renderDomainKnobValueRegistry(buildDomainKnobValueRegistry(spec, "cohort_default")),
    "utf-8",
  );
  return { root, cleanup: () => rmSync(repoRoot, { recursive: true, force: true }) };
}

class ScriptedLlm {
  constructor(private readonly response: unknown) {}
  withStructuredOutput(_schema: unknown) {
    return { invoke: async (_input: unknown) => this.response };
  }
  // biome-ignore lint/suspicious/noExplicitAny: unused free-text path
  async invoke(_m: any): Promise<any> {
    throw new Error("free-text path not expected");
  }
}

function fakeApi(overrides: Partial<BridgeApi> = {}): BridgeApi {
  return {
    scorecardListSkill: async () => ({
      rows: [{ agent: "volatility", mean_alpha_5d: 0.01, sharpe_window: 0.5, n_obs: 12 }],
    }),
    darwinianGetWeights: async () => ({
      weights: { volatility: { weight: 0.8, sharpe_30: 0.3, sharpe_90: 0.4, quartile: 3 } },
    }),
    ...overrides,
  } as unknown as BridgeApi;
}

function llmReturning(mutation: Record<string, unknown>): ScriptedLlm {
  return new ScriptedLlm(mutation);
}

describe("mutate", () => {
  let fake: FakeRoot;
  beforeEach(() => {
    fake = makeRoot();
    clearPromptCache();
  });
  afterEach(() => fake?.cleanup());

  const goodMutation = () => ({
    zh_prompt: ZH.replace("做点事", "做点更精确的事，量化阈值"),
    en_prompt: EN.replace("do stuff", "do precise, quantified things"),
    modification_summary: "tighten wording",
    rationale: "low sharpe suggests vague thresholds",
  });

  it("returns a validated synchronized rewrite", async () => {
    const llm = llmReturning(goodMutation());
    const m = await mutate({
      cohort: "cohort_default",
      agent: "volatility",
      promptsRoot: fake.root,
      deps: { llm: llm as never, api: fakeApi() },
    });
    expect(m.zh_prompt).toContain("更精确");
    expect(m.en_prompt).toContain("precise");
    expect(m.modification_summary).toBe("tighten wording");
  });

  it("throws when the rewrite drops a schema field (guardrail enforced)", async () => {
    const bad = goodMutation();
    bad.zh_prompt = bad.zh_prompt.replace('"regime_filter"', '"regime"');
    await expect(
      mutate({
        cohort: "cohort_default",
        agent: "volatility",
        promptsRoot: fake.root,
        deps: { llm: llmReturning(bad) as never, api: fakeApi() },
      }),
    ).rejects.toThrow(PromptInvariantError);
  });

  it("throws on a no-op rewrite", async () => {
    const noop = { ...goodMutation(), zh_prompt: ZH, en_prompt: EN };
    await expect(
      mutate({
        cohort: "cohort_default",
        agent: "volatility",
        promptsRoot: fake.root,
        deps: { llm: llmReturning(noop) as never, api: fakeApi() },
      }),
    ).rejects.toThrow(/no-op/);
  });

  it("still produces a rewrite on cold start (no skill data)", async () => {
    const api = fakeApi({
      scorecardListSkill: async () => ({ rows: [] }),
      darwinianGetWeights: async () => ({ weights: {} }),
    });
    const m = await mutate({
      cohort: "cohort_default",
      agent: "volatility",
      promptsRoot: fake.root,
      deps: { llm: llmReturning(goodMutation()) as never, api },
    });
    expect(m.zh_prompt).toContain("更精确");
  });

  it("generates a fake-llm knob patch instead of rewriting prompt prose", async () => {
    fake.cleanup();
    fake = makeKnobsRoot();

    const m = await mutateResearchKnobs({
      cohort: "cohort_default",
      agent: "volatility",
      promptsRoot: fake.root,
      mutationId: "KM-generic-test",
      fakeLlm: true,
      deps: { llm: llmReturning({}) as never, api: fakeApi() },
    });

    expect(m.modification_summary).toContain("knob patch:");
    expect(m.knob_mutation.knob_patches[0]?.new_value).toBe(0.5);
    expect(m.zh_prompt).toContain("# zh body");
    expect(m.en_prompt).toContain("# en body");
    expect(m.zh_prompt).toContain("cap: 0.5");
    expect(m.en_prompt).toContain("cap: 0.5");
    expect(m.governance_registry_update).toMatchObject({
      relative_path: "registry/prompt_governance/cohort_default/volatility.json",
    });
    expect(m.governance_registry_update?.content).toContain(
      '"last_mutation_id": "KM-generic-test"',
    );
    expect(m.bundled_prompt_update.zh_prompt).toContain("cap: 0.5");
    expect(m.bundled_prompt_update.en_prompt).toContain("cap: 0.5");
    expect(parseResearchKnobsPrompt(m.bundled_prompt_update.zh_prompt).knobs).toEqual(
      parseResearchKnobsPrompt(m.zh_prompt).knobs,
    );
  });

  it("rejects a private prompt whose base projection drifted from bundled", async () => {
    fake.cleanup();
    fake = makeLegacyDecisionRoot();

    await expect(
      mutateResearchKnobs({
        cohort: "cohort_default",
        agent: "cio",
        promptsRoot: fake.root,
        mutationId: "KM-domain-test",
        fakeLlm: true,
        deps: { llm: llmReturning({}) as never, api: fakeApi() },
      }),
    ).rejects.toThrow(/private and bundled base prompt projections do not match/);
  });
});
