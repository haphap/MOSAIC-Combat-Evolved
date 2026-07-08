import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { ResearchKnobs } from "../src/agents/helpers/research_knobs.js";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import type { KnobPatch } from "../src/autoresearch/mutator.js";
import {
  appendKnobMutationMetadataLog,
  applyKnobPatchesToGovernanceRegistry,
  applyKnobPatchesToGovernanceRegistryFile,
  applyKnobPatchesToProjection,
  applyKnobPatchesToPromptPair,
  assertPromptInvariants,
  assertPromptPairInvariants,
  buildKnobMutationMetadata,
  type KnobMutation,
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
    knob_patches: [
      {
        path: "/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/confidence_policy/missing_current_data/cap",
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
      "/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/confidence_policy/missing_current_data/cap: old_value does not match current knobs",
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
      "/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/confidence_policy/missing_current_data/cap: no-op patch",
    );
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

  it("applies concrete learnable-parameter patches to a governance registry payload", () => {
    const knobs = knobsFixture();
    const registry = {
      rule_packs: {
        "macro.central_bank.liquidity.v1": {
          rules: {
            "macro.central_bank.soft.001": {
              learnable_parameters: {
                pboc_liquidity_weight: {
                  value: 0.5,
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
          old_value: 0.5,
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
    ).toBe(0.5);
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
          old_value: 0.5,
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
                      pboc_liquidity_weight: { value: 0.5 },
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
              old_value: 0.5,
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
                old_value: 0.5,
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
      const rows = readFileSync(logPath, "utf-8")
        .trim()
        .split("\n")
        .map((line) => JSON.parse(line) as Record<string, unknown>);
      expect(rows).toHaveLength(1);
      const row = rows[0];
      expect(row).toBeDefined();
      expect(row?.mutation_id).toBe("KM-1");
      expect(row?.decision).toBe("dry_run");
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
  const root = mkdtempSync(join(tmpdir(), "mosaic-knob-mutator-test-"));
  const dir = join(root, "cohort_default", "macro");
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "volatility.zh.md"), knobsFencePrompt("# zh body"), "utf-8");
  writeFileSync(join(dir, "volatility.en.md"), knobsFencePrompt("# en body"), "utf-8");
  return { root, cleanup: () => rmSync(root, { recursive: true, force: true }) };
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
      fakeLlm: true,
      deps: { llm: llmReturning({}) as never, api: fakeApi() },
    });

    expect(m.modification_summary).toContain("knob patch:");
    expect(m.knob_mutation.knob_patches[0]?.new_value).toBe(0.5);
    expect(m.zh_prompt).toContain("# zh body");
    expect(m.en_prompt).toContain("# en body");
    expect(m.zh_prompt).toContain("cap: 0.5");
    expect(m.en_prompt).toContain("cap: 0.5");
  });
});
