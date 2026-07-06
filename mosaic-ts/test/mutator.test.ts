import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import {
  assertPromptInvariants,
  assertPromptPairInvariants,
  MAX_LENGTH_DELTA,
  mutate,
  PROMPT_CONTRACT_REQUIRED_SECTION_CATEGORIES,
  PromptInvariantError,
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

// ── assertPromptInvariants ────────────────────────────────────────────────

describe("assertPromptInvariants", () => {
  it("accepts a focused valid edit", () => {
    const rewritten = ZH.replace("做点事", "做点更精确的事");
    expect(() => assertPromptInvariants(ZH, rewritten)).not.toThrow();
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
});
