/**
 * 7M Step 2: formatMirofishContext + opt-in CIO prompt injection.
 */

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AIMessage, type BaseMessage } from "@langchain/core/messages";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildCioNode } from "../src/agents/decision/cio.js";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import type { DailyCycleStateType } from "../src/agents/state.js";
import type { CioOutput } from "../src/agents/types.js";
import type { BridgeApi, MirofishContext, MosaicConfig } from "../src/bridge/types.js";
import type { LlmHandle } from "../src/llm/factory.js";
import { formatMirofishContext } from "../src/mirofish/context.js";

const FULL: MirofishContext = {
  n_scenarios: 5,
  regime: "RISK_OFF",
  narrative: "急跌回调",
  csi300_return: -0.12,
  hct_ticker: "000300.SH",
  hct_direction: "SHORT",
  hct_csi300_return: -0.35,
  tail_summary: "Crash: CSI300 -35.0% (p=5%)",
  engine: "swarm",
  date: "2026-05-30",
};

describe("formatMirofishContext", () => {
  it("formats a full context with the disclaimer", () => {
    const out = formatMirofishContext(FULL);
    expect(out).toContain("前瞻情景参考");
    expect(out).toContain("RISK_OFF");
    expect(out).toContain("000300.SH SHORT");
    expect(out).toContain("Crash");
    expect(out).toContain("仅供参考"); // disclaimer always present
  });

  it("returns null for null / all-empty context", () => {
    expect(formatMirofishContext(null)).toBeNull();
    expect(formatMirofishContext(undefined)).toBeNull();
    expect(
      formatMirofishContext({ ...FULL, regime: null, hct_direction: null, tail_summary: null }),
    ).toBeNull();
  });

  it("degrades cleanly when tail / hct are null", () => {
    const out = formatMirofishContext({ ...FULL, hct_direction: null, tail_summary: null });
    expect(out).toContain("RISK_OFF");
    expect(out).not.toContain("最高信念方向");
    expect(out).not.toContain("尾部风险");
    expect(out).toContain("仅供参考");
  });

  it("localizes labels + disclaimer to English when language is en", () => {
    const out = formatMirofishContext(FULL, "en");
    expect(out).toContain("Forward-Looking Context");
    expect(out).toContain("Highest-conviction direction");
    expect(out).toContain("Simulations, not certainties");
    expect(out).not.toContain("前瞻情景参考");
  });

  it("renders 0.0% (not NaN) when a csi field is null", () => {
    const out = formatMirofishContext({ ...FULL, csi300_return: null as unknown as number });
    expect(out).toContain("CSI300 0.0%");
    expect(out).not.toContain("NaN");
  });
});

describe("CIO MiroFish context injection (opt-in)", () => {
  let promptDir: string;

  class ScriptedLlm {
    captured: BaseMessage[] = [];
    response = new AIMessage("analysis text");
    structuredResponse: CioOutput = { agent: "cio", portfolio_actions: [], confidence: 0.3 };
    bindTools(): ScriptedLlm {
      return this;
    }
    withStructuredOutput(): { invoke: (i: unknown) => Promise<unknown> } {
      return { invoke: async () => this.structuredResponse };
    }
    async invoke(messages: BaseMessage[]): Promise<AIMessage> {
      this.captured = messages;
      return this.response;
    }
  }

  const baseConfig = (): MosaicConfig =>
    ({
      llm_provider: "fake",
      deep_think_llm: "fake",
      quick_think_llm: "fake",
      backend_url: null,
      anthropic_base_url: null,
      anthropic_effort: null,
      output_language: "Chinese",
      research_depth_name: "standard",
      active_cohort: "cohort_default",
      cohorts: { cohort_default: { start: "2024-01-01", end: "2024-12-31" } },
      data_vendors: {},
      tool_vendors: {},
    }) as unknown as MosaicConfig;

  const state = (): DailyCycleStateType =>
    ({
      active_cohort: "cohort_default",
      as_of_date: "2024-06-30",
      layer1_outputs: {},
      layer2_outputs: {},
      layer3_outputs: {},
      layer4_outputs: {},
    }) as unknown as DailyCycleStateType;

  function fakeApi(ctx: MirofishContext | null) {
    return {
      mirofishGetContext: vi.fn().mockResolvedValue({ context: ctx }),
    } as unknown as BridgeApi;
  }

  beforeEach(() => {
    promptDir = mkdtempSync(join(tmpdir(), "mosaic-mfctx-"));
    const dir = join(promptDir, "cohort_default", "decision");
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "cio.zh.md"), "FAKE-CIO", "utf-8");
    clearPromptCache();
  });
  afterEach(() => {
    rmSync(promptDir, { recursive: true, force: true });
    clearPromptCache();
  });

  function humanText(llm: ScriptedLlm): string {
    const human = llm.captured[1];
    return typeof human?.content === "string" ? human.content : JSON.stringify(human?.content);
  }

  it("does NOT inject when toggle is off (default)", async () => {
    const llm = new ScriptedLlm();
    const handle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake",
    } as LlmHandle;
    const api = fakeApi(FULL);
    const node = buildCioNode({
      llmHandle: handle,
      api,
      config: baseConfig(),
      promptsRoot: promptDir,
    });
    await node(state());
    expect(api.mirofishGetContext).not.toHaveBeenCalled();
    expect(humanText(llm)).not.toContain("前瞻情景参考");
  });

  it("injects the context section when toggle is on", async () => {
    const llm = new ScriptedLlm();
    const handle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake",
    } as LlmHandle;
    const api = fakeApi(FULL);
    const config = { ...baseConfig(), mirofish: { inject_context: true } } as MosaicConfig;
    const node = buildCioNode({ llmHandle: handle, api, config, promptsRoot: promptDir });
    await node(state());
    expect(api.mirofishGetContext).toHaveBeenCalledOnce();
    expect(api.mirofishGetContext).toHaveBeenCalledWith({ as_of_date: "2024-06-30" });
    expect(humanText(llm)).toContain("前瞻情景参考");
    expect(humanText(llm)).toContain("仅供参考");
  });

  it("toggle on but no context → no section, no throw", async () => {
    const llm = new ScriptedLlm();
    const handle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake",
    } as LlmHandle;
    const api = fakeApi(null);
    const config = { ...baseConfig(), mirofish: { inject_context: true } } as MosaicConfig;
    const node = buildCioNode({ llmHandle: handle, api, config, promptsRoot: promptDir });
    await node(state());
    expect(humanText(llm)).not.toContain("前瞻情景参考");
  });
});
