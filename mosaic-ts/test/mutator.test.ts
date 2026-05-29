import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import {
  assertPromptInvariants,
  MAX_LENGTH_DELTA,
  mutate,
  PromptInvariantError,
} from "../src/autoresearch/mutator.js";
import type { BridgeApi } from "../src/bridge/types.js";

const ZH = `# volatility\n\n## 工作流程\n做点事\n\n## 输出 schema\n\n\`\`\`json\n{ "agent": "volatility", "regime_filter": "x", "confidence": 0 }\n\`\`\`\n`;
const EN = `# volatility\n\n## Workflow\ndo stuff\n\n## Output schema\n\n\`\`\`json\n{ "agent": "volatility", "regime_filter": "x", "confidence": 0 }\n\`\`\`\n`;

// ── assertPromptInvariants ────────────────────────────────────────────────

describe("assertPromptInvariants", () => {
  it("accepts a focused valid edit", () => {
    const rewritten = ZH.replace("做点事", "做点更精确的事");
    expect(() => assertPromptInvariants(ZH, rewritten)).not.toThrow();
  });

  it("rejects a dropped section", () => {
    const rewritten = ZH.replace("## 输出 schema", "## 别的");
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
