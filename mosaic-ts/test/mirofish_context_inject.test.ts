/**
 * 7M Step 2: formatMirofishContext + configurable L4 prompt injection.
 */

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AIMessage, type BaseMessage } from "@langchain/core/messages";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { disableManifestResearchKnobsForLegacyFixtures } from "./helpers/research_knobs_env.js";

disableManifestResearchKnobsForLegacyFixtures();

import { buildAutonomousExecutionNode } from "../src/agents/decision/autonomous_execution.js";
import { buildCioNode } from "../src/agents/decision/cio.js";
import { buildCroNode } from "../src/agents/decision/cro.js";
import {
  emptyLayer4RuntimeState,
  freezeCioProposal,
} from "../src/agents/decision/layer4_runtime.js";
import { AgentRunContractError } from "../src/agents/helpers/agent_run_contract.js";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import type { DailyCycleStateType } from "../src/agents/state.js";
import type { AutoExecOutput, CioOutput, CroOutput } from "../src/agents/types.js";
import type { BridgeApi, MirofishContext, MosaicConfig } from "../src/bridge/types.js";
import type { LlmHandle } from "../src/llm/factory.js";
import { formatMirofishContext } from "../src/mirofish/context.js";

const FULL: MirofishContext = {
  n_scenarios: 5,
  regime: "RISK_OFF",
  narrative: "急跌回调",
  csi300_return: -0.12,
  scenario_count: 5,
  horizon_days: 30,
  as_of_date: "2024-06-30",
  context_hash: "sha256:test_context",
  generator_version: "mirofish_context_v1",
  hct_ticker: "000300.SH",
  hct_direction: "SHORT",
  hct_csi300_return: -0.35,
  tail_summary: "Crash: CSI300 -35.0% (p=5%)",
  position_stress: [
    {
      ticker: "600519.SH",
      tail_loss: -0.12,
      scenario_agreement: 0.8,
      suggested_action: "REDUCE",
    },
  ],
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
    expect(out).toContain("600519.SH tail=-12.0% agree=80.0% action=REDUCE");
    expect(out).toContain(
      "scenarios=5 horizon_days=30 as_of_date=2024-06-30 context_hash=sha256:test_context",
    );
    expect(out).toContain("generator_version=mirofish_context_v1");
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

describe("CIO MiroFish context injection", () => {
  let promptDir: string;

  class ScriptedLlm {
    captured: BaseMessage[][] = [];
    response = new AIMessage("analysis text");
    structuredResponses: Array<CroOutput | AutoExecOutput | CioOutput> = [
      { agent: "cio", portfolio_actions: [], confidence: 0.3 },
    ];
    bindTools(): ScriptedLlm {
      return this;
    }
    withStructuredOutput(): { invoke: (i: unknown) => Promise<unknown> } {
      return {
        invoke: async () =>
          this.structuredResponses.shift() ?? {
            agent: "cio",
            portfolio_actions: [],
            confidence: 0.3,
          },
      };
    }
    async invoke(messages: BaseMessage[]): Promise<AIMessage> {
      this.captured.push(messages);
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
      layer4_outputs: {
        cro: null,
        alpha_discovery: null,
        autonomous_execution: null,
        cio: null,
      },
      current_positions: {
        snapshot_status: "empty_confirmed",
        position_source: "empty_confirmed",
        source_error_code: null,
        position_snapshot_hash: "sha256:empty_positions",
        positions: [],
      },
      portfolio_actions: [],
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
    writeFileSync(join(dir, "cro.zh.md"), "FAKE-CRO", "utf-8");
    writeFileSync(join(dir, "autonomous_execution.zh.md"), "FAKE-AUTO", "utf-8");
    writeFileSync(join(dir, "cio.zh.md"), "FAKE-CIO", "utf-8");
    clearPromptCache();
  });
  afterEach(() => {
    rmSync(promptDir, { recursive: true, force: true });
    clearPromptCache();
  });

  function humanText(llm: ScriptedLlm): string {
    const human = llm.captured.at(-1)?.[1];
    return typeof human?.content === "string" ? human.content : JSON.stringify(human?.content);
  }

  function allHumanText(llm: ScriptedLlm): string[] {
    return llm.captured.map((messages) => {
      const human = messages[1];
      return typeof human?.content === "string" ? human.content : JSON.stringify(human?.content);
    });
  }

  it("does NOT inject when the runtime config omits the toggle", async () => {
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
    await expect(node(state())).rejects.toBeInstanceOf(AgentRunContractError);
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
    await expect(node(state())).rejects.toBeInstanceOf(AgentRunContractError);
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
    await expect(node(state())).rejects.toBeInstanceOf(AgentRunContractError);
    expect(humanText(llm)).not.toContain("前瞻情景参考");
  });

  it("toggle on but missing as_of_date disables context injection", async () => {
    const llm = new ScriptedLlm();
    const handle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake",
    } as LlmHandle;
    const { as_of_date: _asOfDate, ...withoutAsOf } = FULL;
    const api = fakeApi(withoutAsOf as MirofishContext);
    const logs: string[] = [];
    const config = { ...baseConfig(), mirofish: { inject_context: true } } as MosaicConfig;
    const node = buildCioNode({
      llmHandle: handle,
      api,
      config,
      promptsRoot: promptDir,
      onLog: (msg) => logs.push(msg),
    });
    await expect(node(state())).rejects.toBeInstanceOf(AgentRunContractError);
    expect(humanText(llm)).not.toContain("前瞻情景参考");
    expect(logs.join("\n")).toContain("mirofish context disabled: missing as_of_date");
  });

  it("toggle on but future as_of_date disables context injection", async () => {
    const llm = new ScriptedLlm();
    const handle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake",
    } as LlmHandle;
    const api = fakeApi({ ...FULL, as_of_date: "2024-07-01" });
    const logs: string[] = [];
    const config = { ...baseConfig(), mirofish: { inject_context: true } } as MosaicConfig;
    const node = buildCioNode({
      llmHandle: handle,
      api,
      config,
      promptsRoot: promptDir,
      onLog: (msg) => logs.push(msg),
    });
    await expect(node(state())).rejects.toBeInstanceOf(AgentRunContractError);
    expect(humanText(llm)).not.toContain("前瞻情景参考");
    expect(logs.join("\n")).toContain("mirofish context disabled: as_of_date 2024-07-01");
  });

  it("toggle on but incomplete scenario metadata disables context injection", async () => {
    const llm = new ScriptedLlm();
    const handle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake",
    } as LlmHandle;
    const {
      scenario_count: _scenarioCount,
      horizon_days: _horizonDays,
      context_hash: _contextHash,
      generator_version: _generatorVersion,
      ...missingMetadata
    } = FULL;
    const api = fakeApi(missingMetadata as MirofishContext);
    const logs: string[] = [];
    const config = { ...baseConfig(), mirofish: { inject_context: true } } as MosaicConfig;
    const node = buildCioNode({
      llmHandle: handle,
      api,
      config,
      promptsRoot: promptDir,
      onLog: (msg) => logs.push(msg),
    });
    await expect(node(state())).rejects.toBeInstanceOf(AgentRunContractError);
    expect(humanText(llm)).not.toContain("前瞻情景参考");
    expect(logs.join("\n")).toContain(
      "mirofish context disabled: missing required metadata scenario_count,horizon_days,context_hash,generator_version",
    );
  });

  it("shares one context lookup and context_hash across CRO, execution, and CIO", async () => {
    const llm = new ScriptedLlm();
    llm.structuredResponses = [
      {
        agent: "cro",
        rejected_picks: [],
        correlated_risks: [],
        black_swan_scenarios: [],
        confidence: 0.3,
      },
      { agent: "autonomous_execution", trades: [], confidence: 0.3 },
      { agent: "cio", portfolio_actions: [], confidence: 0.3 },
    ];
    const handle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fake",
    } as LlmHandle;
    const api = {
      mirofishGetContext: vi
        .fn()
        .mockResolvedValueOnce({ context: FULL })
        .mockResolvedValueOnce({
          context: { ...FULL, context_hash: "sha256:unexpected_second_context" },
        }),
    } as unknown as BridgeApi;
    const config = { ...baseConfig(), mirofish: { inject_context: true } } as MosaicConfig;
    const deps = { llmHandle: handle, api, config, promptsRoot: promptDir };
    const staged = state();
    const proposal = freezeCioProposal(staged, {
      agent: "cio",
      portfolio_actions: [],
      confidence: 0.3,
    });
    staged.layer4_outputs.runtime = {
      ...emptyLayer4RuntimeState(),
      cio_proposal: proposal.proposal,
      candidate_target_state: proposal.candidate,
      position_review_state: proposal.reviews,
      portfolio_exposure_state: proposal.exposure,
    };
    await expect(buildCroNode(deps)(staged)).rejects.toBeInstanceOf(AgentRunContractError);
    await expect(buildAutonomousExecutionNode(deps)(staged)).rejects.toBeInstanceOf(
      AgentRunContractError,
    );
    await expect(buildCioNode(deps)(staged)).rejects.toBeInstanceOf(AgentRunContractError);

    expect(api.mirofishGetContext).toHaveBeenCalledOnce();
    const renderedContexts = allHumanText(llm);
    expect(renderedContexts).toHaveLength(3);
    expect(
      renderedContexts.every((text) => text.includes("context_hash=sha256:test_context")),
    ).toBe(true);
    expect(renderedContexts.join("\n")).not.toContain("unexpected_second_context");
  });
});
