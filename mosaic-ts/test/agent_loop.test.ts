import { AIMessage, type BaseMessage, HumanMessage, ToolMessage } from "@langchain/core/messages";
import { tool } from "@langchain/core/tools";
import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";
import {
  compactToolOutput,
  parseToolOutputMaxChars,
  pruneConsumedToolHistory,
  pruneConsumedToolHistoryWithEntries,
  resolveToolOutputMaxChars,
  runAgentToolLoop,
  toolArgsFingerprint,
  toolCallFingerprint,
  toolResultFingerprint,
} from "../src/agents/helpers/agent_loop.js";
import {
  type BridgeApi,
  bridgeToolFromMetadata,
  INVALID_PARAMS,
  RpcError,
} from "../src/bridge/index.js";
import { BRIDGE_INITIAL_TOOL_INVOKE } from "../src/bridge/tools.js";

class ScriptedLlm {
  bindToolsCalled = 0;
  boundToolNames: string[] = [];
  readonly seenMessages: BaseMessage[][] = [];
  readonly invokeOptions: unknown[] = [];

  constructor(private readonly responses: AIMessage[]) {}

  bindTools(tools: ReadonlyArray<{ name: string }>): ScriptedLlm {
    this.bindToolsCalled++;
    this.boundToolNames = tools.map((tool) => tool.name);
    return this;
  }

  async invoke(messages: BaseMessage[], options?: unknown): Promise<AIMessage> {
    this.seenMessages.push(messages);
    this.invokeOptions.push(options);
    const next = this.responses.shift();
    if (!next) throw new Error("script exhausted");
    return next;
  }
}

describe("agent tool loop helpers", () => {
  afterEach(() => vi.unstubAllEnvs());

  it.each([
    undefined,
    "0",
    "false",
    "true",
    "1",
  ])("requires explicit RKE opt-in for initial collection and model calls: %s", async (setting) => {
    vi.stubEnv("MOSAIC_RKE_ENABLED", setting);
    const enabled = setting === "1";
    const executions: string[] = [];
    const rkeName = "get_rke_research_context";
    const llm = new ScriptedLlm([
      new AIMessage({
        content: "",
        tool_calls: [{ id: "rke", name: rkeName, args: { query: "adaptive" } }],
      }),
      new AIMessage("done"),
    ]);
    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: ["get_current", rkeName].map((name) =>
        tool(
          async ({ query }) => {
            executions.push(`${name}:${query}`);
            return name === rkeName ? "Research case FCRED-test" : "current evidence";
          },
          { name, description: "test", schema: z.object({ query: z.string() }) },
        ),
      ),
      initialToolCalls: ["get_current", rkeName].map((name) => ({
        name,
        args: { query: "initial" },
      })),
      reserveRkeQuery: true,
      systemMessage: "system",
      initialMessages: [],
    });
    expect(llm.boundToolNames).toEqual(enabled ? ["get_current", rkeName] : ["get_current"]);
    expect(executions).toEqual(
      enabled
        ? ["get_current:initial", `${rkeName}:initial`, `${rkeName}:adaptive`]
        : ["get_current:initial"],
    );
    expect(result.toolExecutions).toBe(enabled ? 3 : 1);
    expect(JSON.stringify(llm.seenMessages).includes("FCRED-test")).toBe(enabled);
    expect(String(llm.seenMessages[0]?.[0]?.content).includes("RKE is disabled")).toBe(!enabled);
    expect(String(llm.seenMessages[0]?.[0]?.content)).not.toContain("reserved for");
  });

  it.each([undefined, "1"])("gates snapshot-only initial RKE collection: %s", async (setting) => {
    vi.stubEnv("MOSAIC_RKE_ENABLED", setting);
    const invokeRke = vi.fn(async () => "Research case FCRED-initial");
    const llm = new ScriptedLlm([new AIMessage("done")]);
    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [
        tool(invokeRke, {
          name: "get_rke_research_context",
          description: "test",
          schema: z.object({}),
        }),
      ],
      initialToolCalls: [{ name: "get_rke_research_context", args: {} }],
      allowModelToolCalls: false,
      systemMessage: "system",
      initialMessages: [],
      maxLoops: 0,
    });
    expect(invokeRke).toHaveBeenCalledTimes(setting === "1" ? 1 : 0);
    expect(result.toolCalls).toBe(setting === "1" ? 1 : 0);
    expect(llm.bindToolsCalled).toBe(0);
    expect(JSON.stringify(llm.seenMessages).includes("FCRED-initial")).toBe(setting === "1");
    expect(String(llm.seenMessages[0]?.[0]?.content).includes("RKE is disabled")).toBe(
      setting !== "1",
    );
  });

  it("forwards the agent timeout signal to LLM analysis calls", async () => {
    const signal = new AbortController().signal;
    const initial = new ScriptedLlm([new AIMessage("done")]);
    await runAgentToolLoop({
      llm: initial as never,
      tools: [],
      systemMessage: "system",
      initialMessages: [new HumanMessage("initial")],
      signal,
    });
    expect(initial.invokeOptions).toEqual([{ signal }]);

    const exhausted = new ScriptedLlm([new AIMessage("forced final")]);
    await runAgentToolLoop({
      llm: exhausted as never,
      tools: [],
      systemMessage: "system",
      initialMessages: [new HumanMessage("initial")],
      maxLoops: 0,
      signal,
    });
    expect(exhausted.invokeOptions).toEqual([{ signal }]);
  });

  it("returns immediately on a final without an opt-in completion guard", async () => {
    const llm = new ScriptedLlm([new AIMessage("done"), new AIMessage("unexpected")]);
    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [],
      systemMessage: "system",
      initialMessages: [new HumanMessage("initial")],
      maxLoops: 3,
    });

    expect(result.analysisText).toBe("done");
    expect(result.llmInvocations).toBe(1);
  });

  it("does not truncate tool output by default", () => {
    expect(resolveToolOutputMaxChars(undefined, undefined)).toBe(0);
    expect(compactToolOutput("a".repeat(10_000), 0)).toEqual({
      text: "a".repeat(10_000),
      truncated: false,
      originalChars: 10_000,
    });
  });

  it("allows explicit tool-output truncation", () => {
    const compacted = compactToolOutput("a".repeat(10_000), 4096);

    expect(compacted.truncated).toBe(true);
    expect(compacted.originalChars).toBe(10_000);
    expect(compacted.text.length).toBeLessThanOrEqual(4096);
    expect(compacted.text).toContain("tool_output_truncated original_chars=10000");
  });

  it("allows tool-output compaction to be disabled", () => {
    expect(parseToolOutputMaxChars("off")).toBe(0);
    expect(resolveToolOutputMaxChars(undefined, "128")).toBe(128);
    expect(compactToolOutput("abc", 0)).toEqual({
      text: "abc",
      truncated: false,
      originalChars: 3,
    });
  });

  it("rejects invalid tool-output caps", () => {
    expect(() => parseToolOutputMaxChars("4k")).toThrow("invalid tool output max chars");
    expect(() => parseToolOutputMaxChars("-1")).toThrow("invalid tool output max chars");
  });

  it("keeps single consumed tool results full in replay history", () => {
    const fullOutput = "x".repeat(900);
    const pruned = pruneConsumedToolHistory([
      new HumanMessage("initial context"),
      new AIMessage({
        content: "retain this short conclusion",
        tool_calls: [
          {
            id: "c1",
            name: "get_big_table",
            args: { ticker: "600519.SH" },
            type: "tool_call",
          },
        ],
      }),
      new ToolMessage({
        content: fullOutput,
        tool_call_id: "c1",
      }),
      new AIMessage("next step"),
    ]);

    expect(pruned.map((message) => message.getType())).toEqual(["human", "ai", "human", "ai"]);
    expect(String(pruned[1]?.content)).toBe("retain this short conclusion");
    expect(String(pruned[2]?.content)).toContain("Prior tool results retained");
    expect(String(pruned[2]?.content)).toContain("get_big_table#");
    expect(String(pruned[2]?.content)).toContain("[full]");
    expect(String(pruned[2]?.content)).toContain(fullOutput);
    expect(String(pruned[2]?.content)).not.toContain("prior_tool_output_compacted");
  });

  it("keeps only the latest repeated fingerprint full across replay pruning", () => {
    const firstOutput = "old-duplicate-".repeat(100);
    const first = pruneConsumedToolHistoryWithEntries(
      [
        new HumanMessage("initial context"),
        new AIMessage({
          content: "",
          tool_calls: [
            {
              id: "c1",
              name: "get_big_table",
              args: { ticker: "600519.SH" },
              type: "tool_call",
            },
          ],
        }),
        new ToolMessage({ content: firstOutput, tool_call_id: "c1" }),
      ],
      [],
    );
    const second = pruneConsumedToolHistoryWithEntries(
      [
        ...first.messages,
        new AIMessage({
          content: "",
          tool_calls: [
            {
              id: "c2",
              name: "get_big_table",
              args: { ticker: "600519.SH" },
              type: "tool_call",
            },
          ],
        }),
        new ToolMessage({ content: "latest full output", tool_call_id: "c2" }),
      ],
      first.entries,
    );

    const replay = second.messages.map((message) => String(message.content)).join("\n");
    expect(replay).toContain("[older_duplicate_memo]");
    expect(replay).toContain("prior_tool_output_compacted");
    expect(replay).not.toContain(firstOutput);
    expect(replay).toContain("[full]");
    expect(replay).toContain("latest full output");
  });

  it("demotes oldest full replay entries when the full replay budget is exceeded", () => {
    const pruned = pruneConsumedToolHistoryWithEntries(
      [
        new HumanMessage("initial context"),
        new AIMessage({
          content: "",
          tool_calls: [
            { id: "c1", name: "get_a", args: { a: 1 }, type: "tool_call" },
            { id: "c2", name: "get_b", args: { b: 2 }, type: "tool_call" },
          ],
        }),
        new ToolMessage({ content: "old full output", tool_call_id: "c1" }),
        new ToolMessage({ content: "new full output", tool_call_id: "c2" }),
      ],
      [],
      "new full output".length,
    );

    const replay = pruned.messages.map((message) => String(message.content)).join("\n");
    expect(replay).toContain("get_a#");
    expect(replay).toContain("[full_budget_memo]");
    expect(replay).toContain("get_b#");
    expect(replay).toContain("[full]");
    expect(replay).toContain("new full output");
  });

  it("builds stable short tool-call fingerprints from canonical args", () => {
    expect(toolCallFingerprint("get_x", { b: 2, a: 1 })).toBe(
      toolCallFingerprint("get_x", { a: 1, b: 2 }),
    );
    expect(toolCallFingerprint("get_x", { a: 1 })).not.toBe(toolCallFingerprint("get_x", { a: 2 }));
  });

  it("builds canonical full hashes for args and JSON results", () => {
    expect(toolArgsFingerprint({ b: 2, a: 1 })).toBe(toolArgsFingerprint({ a: 1, b: 2 }));
    expect(toolResultFingerprint('{"b":2,"a":1}')).toBe(toolResultFingerprint('{"a":1,"b":2}'));
    expect(toolResultFingerprint("plain text")).not.toBe(toolResultFingerprint("plain text "));
    expect(toolArgsFingerprint({ a: 1 })).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(toolResultFingerprint("result")).toMatch(/^sha256:[0-9a-f]{64}$/);
  });

  it("serves repeated same-args tool calls from the per-agent cache", async () => {
    const llm = new ScriptedLlm([
      new AIMessage({
        content: "",
        tool_calls: [
          {
            id: "c1",
            name: "get_china_macro_snapshot",
            args: { a: 1 },
            type: "tool_call",
          },
        ],
      }),
      new AIMessage({
        content: "",
        tool_calls: [
          {
            id: "c2",
            name: "get_china_macro_snapshot",
            args: { a: 1 },
            type: "tool_call",
          },
        ],
      }),
      new AIMessage("done"),
    ]);
    let executions = 0;
    const logs: string[] = [];
    const getX = tool(
      async () => {
        executions++;
        return `result-${executions}`;
      },
      {
        name: "get_china_macro_snapshot",
        description: "test tool",
        schema: z.object({ a: z.number() }),
      },
    );

    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [getX],
      systemMessage: "system",
      initialMessages: [new HumanMessage("initial")],
      agentInvocationId: "run-1:get_x:agent_run",
      onLog: (message) => logs.push(message),
    });

    expect(result.analysisText).toBe("done");
    expect(result.toolCalls).toBe(2);
    expect(result.toolExecutions).toBe(1);
    expect(result.toolCacheHits).toBe(1);
    expect(executions).toBe(1);
    expect(logs.some((line) => line.includes("tool_cache_hit"))).toBe(true);
    expect(result.toolStatuses).toHaveLength(2);
    expect(result.toolStatuses[0]).toEqual(
      expect.objectContaining({
        call_id: "c1",
        agent_invocation_id: "run-1:get_x:agent_run",
        cache_hit: false,
        failed: false,
      }),
    );
    expect(result.toolStatuses[1]).toEqual(
      expect.objectContaining({ call_id: "c2", cache_hit: true, failed: false }),
    );
    expect(result.toolStatuses[0]?.args_fingerprint).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(result.toolStatuses[0]?.result_fingerprint).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(result.toolStatuses[0]?.source_fingerprint).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(result.toolStatuses[1]?.result_fingerprint).toBe(
      result.toolStatuses[0]?.result_fingerprint,
    );
    expect(result.toolStatuses[1]?.source_fingerprint).toBe(
      result.toolStatuses[0]?.source_fingerprint,
    );
    expect(
      result.messages
        .filter((message) => message.getType() === "tool")
        .map((message) => String(message.content)),
    ).toEqual(["result-1", "result-1"]);
  });

  it("uses an opt-in completion guard to reach exact calls after membership", async () => {
    const llm = new ScriptedLlm([
      new AIMessage({
        content: "",
        tool_calls: [
          {
            id: "membership-1",
            name: "get_sector_index_membership",
            args: { request: "membership" },
            type: "tool_call",
          },
        ],
      }),
      new AIMessage("premature final"),
      new AIMessage({
        content: "",
        tool_calls: [
          {
            id: "exact-1",
            name: "get_stock_data",
            args: { ticker: "member-a" },
            type: "tool_call",
          },
          {
            id: "exact-2",
            name: "get_stock_data",
            args: { ticker: "member-b" },
            type: "tool_call",
          },
        ],
      }),
      new AIMessage("final selection"),
    ]);
    const membership = tool(async () => "membership result", {
      name: "get_sector_index_membership",
      description: "membership",
      schema: z.object({ request: z.string() }),
    });
    const stockData = tool(async ({ ticker }) => `data for ${ticker}`, {
      name: "get_stock_data",
      description: "exact stock data",
      schema: z.object({ ticker: z.string() }),
    });

    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [membership, stockData],
      systemMessage: "system",
      initialMessages: [new HumanMessage("initial")],
      maxLoops: 3,
      completionGuard: ({ toolStatuses }) =>
        toolStatuses.length === 1
          ? "Call two different returned members with the exact tool before finalizing."
          : undefined,
    });

    expect(result.analysisText).toBe("final selection");
    expect(result.toolCalls).toBe(3);
    expect(result.toolExecutions).toBe(3);
    expect(result.toolStatuses.map((status) => status.name)).toEqual([
      "get_sector_index_membership",
      "get_stock_data",
      "get_stock_data",
    ]);
  });

  it.each([
    "runtime membership exact request is outside the allowlist",
    "runtime membership exact request arguments are invalid",
  ])("does not spend model tool budget on an admission rejection: %s", async (rejectionMessage) => {
    const llm = new ScriptedLlm([
      new AIMessage({
        content: "",
        tool_calls: [
          {
            id: "membership-1",
            name: "get_sector_index_membership",
            args: { request: "membership" },
            type: "tool_call",
          },
        ],
      }),
      new AIMessage({
        content: "",
        tool_calls: [
          {
            id: "exact-1",
            name: "get_stock_data",
            args: { ticker: "member-a" },
            type: "tool_call",
          },
          {
            id: "exact-rejected",
            name: "get_stock_data",
            args: { ticker: "member-b" },
            type: "tool_call",
          },
        ],
      }),
      new AIMessage("premature final"),
      new AIMessage({
        content: "",
        tool_calls: [
          {
            id: "exact-2",
            name: "get_stock_data",
            args: { ticker: "member-c" },
            type: "tool_call",
          },
        ],
      }),
      new AIMessage("final selection"),
    ]);
    const dataTransportTickers: string[] = [];
    const membership = tool(async () => "membership result", {
      name: "get_sector_index_membership",
      description: "membership",
      schema: z.object({ request: z.string() }),
    });
    const stockData = tool(
      async ({ ticker }) => {
        if (ticker === "member-b") {
          throw new RpcError("tools.call", INVALID_PARAMS, rejectionMessage);
        }
        dataTransportTickers.push(ticker);
        return `data for ${ticker}`;
      },
      {
        name: "get_stock_data",
        description: "exact stock data",
        schema: z.object({ ticker: z.string() }),
      },
    );

    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [membership, stockData],
      systemMessage: "system",
      initialMessages: [new HumanMessage("initial")],
      maxLoops: 4,
      completionGuard: ({ step, toolStatuses }) =>
        step === 2 &&
        toolStatuses.some((status) => status.call_id === "exact-1" && !status.failed) &&
        toolStatuses.some((status) => status.call_id === "exact-rejected" && status.failed)
          ? "Call one different returned member before finalizing."
          : undefined,
    });

    expect(result.toolCalls).toBe(4);
    expect(result.toolExecutions).toBe(3);
    expect(result.llmInvocations).toBe(5);
    expect(result.analysisText).toBe("final selection");
    expect(dataTransportTickers).toEqual(["member-a", "member-c"]);
    expect(result.toolStatuses).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ call_id: "exact-rejected", failed: true }),
        expect.objectContaining({ call_id: "exact-2", failed: false }),
      ]),
    );
    expect(result.messages.some((message) => String(message.content).includes("-32602"))).toBe(
      true,
    );
  });

  it("grants one bounded repair turn after a final-round admission rejection", async () => {
    const llm = new ScriptedLlm([
      new AIMessage({
        content: "",
        tool_calls: [
          {
            id: "membership-1",
            name: "get_sector_index_membership",
            args: { request: "membership" },
            type: "tool_call",
          },
        ],
      }),
      new AIMessage("premature final"),
      new AIMessage({
        content: "",
        tool_calls: [
          {
            id: "exact-1",
            name: "get_stock_data",
            args: { ticker: "member-a" },
            type: "tool_call",
          },
          {
            id: "exact-rejected",
            name: "get_stock_data",
            args: { ticker: "member-b" },
            type: "tool_call",
          },
        ],
      }),
      new AIMessage("premature final after rejection"),
      new AIMessage({
        content: "",
        tool_calls: [
          {
            id: "exact-2",
            name: "get_stock_data",
            args: { ticker: "member-c" },
            type: "tool_call",
          },
        ],
      }),
      new AIMessage("final selection"),
    ]);
    const dataTransportTickers: string[] = [];
    const membership = tool(async () => "membership result", {
      name: "get_sector_index_membership",
      description: "membership",
      schema: z.object({ request: z.string() }),
    });
    const stockData = tool(
      async ({ ticker }) => {
        if (ticker === "member-b") {
          throw new RpcError(
            "tools.call",
            INVALID_PARAMS,
            "runtime membership exact request is outside the allowlist",
          );
        }
        dataTransportTickers.push(ticker);
        return `data for ${ticker}`;
      },
      {
        name: "get_stock_data",
        description: "exact stock data",
        schema: z.object({ ticker: z.string() }),
      },
    );

    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [membership, stockData],
      systemMessage: "system",
      initialMessages: [new HumanMessage("initial")],
      maxLoops: 4,
      completionGuard: ({ step, toolStatuses }) => {
        if (step === 1 && toolStatuses.length === 1) {
          return "Call two different returned members with the exact tool before finalizing.";
        }
        return step === 3 &&
          toolStatuses.some((status) => status.call_id === "exact-1" && !status.failed) &&
          toolStatuses.some((status) => status.call_id === "exact-rejected" && status.failed)
          ? "Call one different returned member before finalizing."
          : undefined;
      },
    });

    expect(result.analysisText).toBe("final selection");
    expect(result.llmInvocations).toBe(6);
    expect(result.toolCalls).toBe(4);
    expect(result.toolExecutions).toBe(3);
    expect(dataTransportTickers).toEqual(["member-a", "member-c"]);
    expect(result.toolStatuses).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ call_id: "exact-rejected", failed: true }),
        expect.objectContaining({ call_id: "exact-2", failed: false }),
      ]),
    );
  });

  it("never grants more than one repair turn across repeated admission rejections", async () => {
    const exactCall = (id: string, ticker: string) =>
      new AIMessage({
        content: "",
        tool_calls: [{ id, name: "get_stock_data", args: { ticker }, type: "tool_call" as const }],
      });
    const llm = new ScriptedLlm([
      exactCall("exact-rejected-1", "member-a"),
      exactCall("exact-rejected-2", "member-b"),
      new AIMessage("forced final"),
    ]);
    const stockData = tool(
      async () => {
        throw new RpcError(
          "tools.call",
          INVALID_PARAMS,
          "runtime membership exact request is outside the allowlist",
        );
      },
      {
        name: "get_stock_data",
        description: "exact stock data",
        schema: z.object({ ticker: z.string() }),
      },
    );

    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [stockData],
      systemMessage: "system",
      initialMessages: [new HumanMessage("initial")],
      maxLoops: 1,
    });

    expect(result.llmInvocations).toBe(3);
    expect(result.toolCalls).toBe(2);
    expect(result.toolExecutions).toBe(0);
  });

  it("still spends tool budget on non-admission failures", async () => {
    const llm = new ScriptedLlm([
      new AIMessage({
        content: "",
        tool_calls: [{ id: "call-1", name: "get_x", args: { value: 1 }, type: "tool_call" }],
      }),
      new AIMessage({
        content: "",
        tool_calls: [{ id: "call-2", name: "get_x", args: { value: 2 }, type: "tool_call" }],
      }),
      new AIMessage({
        content: "",
        tool_calls: [{ id: "call-3", name: "get_x", args: { value: 3 }, type: "tool_call" }],
      }),
      new AIMessage("final selection"),
    ]);
    const toolCalls: number[] = [];
    const getX = tool(
      async ({ value }) => {
        toolCalls.push(value);
        if (value === 1) {
          throw new RpcError("tools.call", INVALID_PARAMS, "some other invalid params");
        }
        return `result:${value}`;
      },
      {
        name: "get_x",
        description: "test tool",
        schema: z.object({ value: z.number() }),
      },
    );

    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [getX],
      systemMessage: "system",
      initialMessages: [new HumanMessage("initial")],
      maxLoops: 3,
    });

    expect(toolCalls).toEqual([1, 2, 3]);
    expect(result.toolCalls).toBe(3);
    expect(result.toolExecutions).toBe(3);
    expect(result.toolStatuses[0]).toEqual(expect.objectContaining({ failed: true }));
    expect(String(llm.seenMessages[1]?.[0]?.content)).toContain("remaining budget is 2");
  });

  it("reuses one server result event when an audited Bridge call hits the cache", async () => {
    const llm = new ScriptedLlm([
      new AIMessage({
        content: "",
        tool_calls: [{ id: "c1", name: "get_x", args: { a: 1 }, type: "tool_call" }],
      }),
      new AIMessage({
        content: "",
        tool_calls: [{ id: "c2", name: "get_x", args: { a: 1 }, type: "tool_call" }],
      }),
      new AIMessage("done"),
    ]);
    const audit = {
      schema_version: "tool_call_audit_v1" as const,
      result_event_id: "tool_evt_cache",
      result_event_hash: `sha256:${"4".repeat(64)}`,
      status: "SUCCEEDED" as const,
      result_authority_type: "SNAPSHOT_BUILD" as const,
      result_authority_hash: `sha256:${"5".repeat(64)}`,
      tool_environment_hash: `sha256:${"7".repeat(64)}`,
      execution_behavior_release_hash: `sha256:${"8".repeat(64)}`,
      capability_bundle_hash: `sha256:${"9".repeat(64)}`,
      knot_coverage_manifest_v2_hash: `sha256:${"a".repeat(64)}`,
      knot_audit_capability_track_v2_hash: `sha256:${"b".repeat(64)}`,
      binding_result_refs: [
        {
          binding_id: "binding_cache",
          binding_result_fingerprint: `sha256:${"6".repeat(64)}`,
        },
      ],
    };
    let rpcCalls = 0;
    const fakeApi = {
      toolsCall: async () => {
        rpcCalls++;
        return { text: "server-result", audit };
      },
    } as unknown as BridgeApi;
    const bridgeTool = bridgeToolFromMetadata(
      fakeApi,
      {
        name: "get_x",
        description: "audited bridge tool",
        args_schema: {
          type: "object",
          properties: { a: { type: "number" } },
          required: ["a"],
        },
      },
      {
        capability: {
          manifest: {
            capability_contract_version: "agent_tool_capability_v1",
            capability_id: "cap_test",
            graph_run_id: "graph_test",
            run_slot_id: "slot_test",
            run_id: "run_test",
            node_id: "china:china",
            agent_id: "china",
            stage: "china",
            allowed_tools: ["get_china_macro_snapshot"],
            as_of: "2026-08-10",
            candidate_scope_hash: null,
            snapshot_bundle_id: "bundle_test",
            snapshot_bundle_hash: `sha256:${"7".repeat(64)}`,
            issued_at: "2026-08-10T00:00:00Z",
            expires_at: "2026-08-10T01:00:00Z",
            nonce: "nonce",
          },
          signing_key_id: "test",
          signature: "hmac-sha256:test",
        },
      },
    );

    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [bridgeTool],
      systemMessage: "system",
      initialMessages: [new HumanMessage("initial")],
    });

    expect(rpcCalls).toBe(1);
    expect(result.toolExecutions).toBe(1);
    expect(result.toolCacheHits).toBe(1);
    expect(result.toolStatuses).toEqual([
      expect.objectContaining({
        call_id: "c1",
        cache_hit: false,
        server_result_event_id: audit.result_event_id,
        server_result_event_hash: audit.result_event_hash,
        server_result_authority_type: audit.result_authority_type,
        server_result_authority_hash: audit.result_authority_hash,
        server_tool_environment_hash: audit.tool_environment_hash,
        server_execution_behavior_release_hash: audit.execution_behavior_release_hash,
        server_capability_bundle_hash: audit.capability_bundle_hash,
        server_knot_coverage_manifest_v2_hash: audit.knot_coverage_manifest_v2_hash,
        server_knot_audit_capability_track_v2_hash: audit.knot_audit_capability_track_v2_hash,
        server_binding_result_refs: audit.binding_result_refs,
      }),
      expect.objectContaining({
        call_id: "c2",
        cache_hit: true,
        server_result_event_id: audit.result_event_id,
        server_result_event_hash: audit.result_event_hash,
        server_result_authority_type: audit.result_authority_type,
        server_result_authority_hash: audit.result_authority_hash,
        server_tool_environment_hash: audit.tool_environment_hash,
        server_execution_behavior_release_hash: audit.execution_behavior_release_hash,
        server_capability_bundle_hash: audit.capability_bundle_hash,
        server_knot_coverage_manifest_v2_hash: audit.knot_coverage_manifest_v2_hash,
        server_knot_audit_capability_track_v2_hash: audit.knot_audit_capability_track_v2_hash,
        server_binding_result_refs: audit.binding_result_refs,
      }),
    ]);
  });

  it("reuses direct frozen result authority from the cache without an audit", async () => {
    const llm = new ScriptedLlm([
      new AIMessage({
        content: "",
        tool_calls: [{ id: "c1", name: "get_x", args: { a: 1 }, type: "tool_call" }],
      }),
      new AIMessage({
        content: "",
        tool_calls: [{ id: "c2", name: "get_x", args: { a: 1 }, type: "tool_call" }],
      }),
      new AIMessage("done"),
    ]);
    const resultAuthority = {
      authority_type: "FROZEN_QUERY" as const,
      authority_hash: `sha256:${"c".repeat(64)}`,
    };
    let rpcCalls = 0;
    const fakeApi = {
      toolsCall: async () => {
        rpcCalls++;
        return { text: "server-result", result_authority: resultAuthority };
      },
    } as unknown as BridgeApi;
    const bridgeTool = bridgeToolFromMetadata(
      fakeApi,
      {
        name: "get_x",
        description: "direct frozen bridge tool",
        args_schema: {
          type: "object",
          properties: { a: { type: "number" } },
          required: ["a"],
        },
      },
      { capability: {} as never },
    );

    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [bridgeTool],
      systemMessage: "system",
      initialMessages: [new HumanMessage("initial")],
    });

    expect(rpcCalls).toBe(1);
    expect(result.toolExecutions).toBe(1);
    expect(result.toolCacheHits).toBe(1);
    expect(result.toolStatuses).toEqual([
      expect.objectContaining({
        call_id: "c1",
        cache_hit: false,
        server_result_authority_type: "FROZEN_QUERY",
        server_result_authority_hash: resultAuthority.authority_hash,
      }),
      expect.objectContaining({
        call_id: "c2",
        cache_hit: true,
        server_result_authority_type: "FROZEN_QUERY",
        server_result_authority_hash: resultAuthority.authority_hash,
      }),
    ]);
    expect(result.toolStatuses[0]).not.toHaveProperty("server_result_event_id");
    expect(result.toolStatuses[0]).not.toHaveProperty("server_tool_environment_hash");
  });

  it("records fallback and as_of metadata from successful and cached tool outputs", async () => {
    const llm = new ScriptedLlm([
      new AIMessage({
        content: "",
        tool_calls: [{ id: "c1", name: "get_x", args: { a: 1 }, type: "tool_call" }],
      }),
      new AIMessage({
        content: "",
        tool_calls: [{ id: "c2", name: "get_x", args: { a: 1 }, type: "tool_call" }],
      }),
      new AIMessage("done"),
    ]);
    const getX = tool(
      async () =>
        JSON.stringify({
          status: "fallback",
          as_of: "2024-06-24",
          rows: [],
        }),
      {
        name: "get_x",
        description: "test tool",
        schema: z.object({ a: z.number() }),
      },
    );

    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [getX],
      systemMessage: "system",
      initialMessages: [new HumanMessage("initial")],
    });

    expect(result.toolStatuses).toEqual([
      expect.objectContaining({
        name: "get_x",
        fallback: true,
        cache_hit: false,
        as_of: "2024-06-24",
      }),
      expect.objectContaining({
        name: "get_x",
        fallback: true,
        cache_hit: true,
        as_of: "2024-06-24",
      }),
    ]);
  });

  it("serves repeated same-args tool failures from the per-agent cache", async () => {
    const llm = new ScriptedLlm([
      new AIMessage({
        content: "",
        tool_calls: [{ id: "c1", name: "get_x", args: { a: 1 }, type: "tool_call" }],
      }),
      new AIMessage({
        content: "",
        tool_calls: [{ id: "c2", name: "get_x", args: { a: 1 }, type: "tool_call" }],
      }),
      new AIMessage("done"),
    ]);
    let executions = 0;
    const logs: string[] = [];
    const getX = tool(
      async () => {
        executions++;
        throw new Error("no rows");
      },
      {
        name: "get_x",
        description: "test tool",
        schema: z.object({ a: z.number() }),
      },
    );

    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [getX],
      systemMessage: "system",
      initialMessages: [new HumanMessage("initial")],
      onLog: (message) => logs.push(message),
    });

    expect(result.analysisText).toBe("done");
    expect(result.toolCalls).toBe(2);
    expect(result.toolExecutions).toBe(1);
    expect(result.toolCacheHits).toBe(1);
    expect(executions).toBe(1);
    expect(logs.some((line) => line.includes("tool_cache_hit"))).toBe(true);
    expect(result.toolStatuses).toEqual([
      expect.objectContaining({ call_id: "c1", failed: true, cache_hit: false }),
      expect.objectContaining({ call_id: "c2", failed: true, cache_hit: true }),
    ]);
    expect(result.toolStatuses[1]?.source_fingerprint).toBe(
      result.toolStatuses[0]?.source_fingerprint,
    );
    expect(
      result.messages
        .filter((message) => message.getType() === "tool")
        .map((message) => String(message.content)),
    ).toEqual(["Tool 'get_x' raised: no rows", "Tool 'get_x' raised: no rows"]);
  });

  it("executes role-required initial tool calls before the first LLM turn", async () => {
    const llm = new ScriptedLlm([new AIMessage("done")]);
    const logs: string[] = [];
    const getFundamentals = tool(async ({ ticker }) => `fundamentals:${ticker}`, {
      name: "get_fundamentals",
      description: "test tool",
      schema: z.object({ ticker: z.string() }),
    });

    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [getFundamentals],
      systemMessage: "system",
      initialMessages: [new HumanMessage("initial")],
      initialToolCalls: [{ name: "get_fundamentals", args: { ticker: "600519.SH" } }],
      onLog: (message) => logs.push(message),
    });

    expect(result.analysisText).toBe("done");
    expect(result.toolCalls).toBe(1);
    expect(result.toolExecutions).toBe(1);
    expect(logs.some((line) => line.includes("names=get_fundamentals"))).toBe(true);
    const firstTurn = llm.seenMessages[0] ?? [];
    expect(
      firstTurn.some(
        (message) =>
          message.getType() === "human" &&
          String(message.content).includes("runtime-provided initial tool evidence") &&
          String(message.content).includes("tool_name=get_fundamentals") &&
          String(message.content).includes("call_id=initial_tool_1") &&
          String(message.content).includes("fundamentals:600519.SH"),
      ),
    ).toBe(true);
    expect(
      firstTurn.some(
        (message) =>
          message.getType() === "ai" && ((message as AIMessage).tool_calls ?? []).length > 0,
      ),
    ).toBe(false);
    expect(firstTurn.some((message) => message.getType() === "tool")).toBe(false);
    expect(
      result.messages.some(
        (message) =>
          message.getType() === "ai" && ((message as AIMessage).tool_calls ?? []).length > 0,
      ),
    ).toBe(true);
    expect(
      result.messages.some(
        (message) => message.getType() === "tool" && String(message.content).includes("600519.SH"),
      ),
    ).toBe(true);
  });

  it("does not replay a repeated initial tool result twice to the model", async () => {
    const output = `initial-result-start:${"x".repeat(10_000)}:initial-result-end`;
    const llm = new ScriptedLlm([
      new AIMessage({
        content: "",
        tool_calls: [
          {
            id: "repeat-initial",
            name: "get_fundamentals",
            args: { ticker: "600519.SH" },
            type: "tool_call",
          },
        ],
      }),
      new AIMessage("done"),
    ]);
    let executions = 0;
    const getFundamentals = tool(
      async () => {
        executions++;
        return output;
      },
      {
        name: "get_fundamentals",
        description: "test tool",
        schema: z.object({ ticker: z.string() }),
      },
    );

    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [getFundamentals],
      systemMessage: "system",
      initialMessages: [new HumanMessage("initial")],
      initialToolCalls: [{ name: "get_fundamentals", args: { ticker: "600519.SH" } }],
    });

    const secondTurn = (llm.seenMessages[1] ?? [])
      .map((message) => String(message.content))
      .join("\n");
    expect(secondTurn.split("initial-result-start")).toHaveLength(2);
    expect(secondTurn).toContain("already supplied as runtime-provided initial evidence");
    expect(executions).toBe(1);
    expect(result.toolCacheHits).toBe(1);
    expect(
      result.messages
        .filter((message) => message.getType() === "tool")
        .map((message) => String(message.content)),
    ).toEqual([output, output]);
  });

  it.each([
    "missing_tool",
    "get_rke_research_context",
  ])("replays missing initial %s as marked human evidence while retaining audit messages", async (toolName) => {
    vi.stubEnv("MOSAIC_RKE_ENABLED", "1");
    const llm = new ScriptedLlm([new AIMessage("done")]);

    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [],
      systemMessage: "system",
      initialMessages: [new HumanMessage("initial")],
      initialToolCalls: [{ name: toolName, args: { ticker: "600519.SH" } }],
    });

    if (toolName === "get_rke_research_context") {
      expect(result.toolStatuses[0]).toMatchObject({
        rke_outcome: "missing_tool",
        dispatched: false,
      });
    }
    const firstTurn = llm.seenMessages[0] ?? [];
    expect(
      firstTurn.some(
        (message) =>
          message.getType() === "human" &&
          String(message.content).includes("runtime-provided initial tool evidence") &&
          String(message.content).includes(`tool_name=${toolName}`) &&
          String(message.content).includes("call_id=initial_tool_1") &&
          String(message.content).includes(`Tool '${toolName}' is not registered`),
      ),
    ).toBe(true);
    expect(firstTurn.some((message) => message.getType() === "tool")).toBe(false);
    expect(
      result.messages.some(
        (message) =>
          message.getType() === "ai" && ((message as AIMessage).tool_calls ?? []).length > 0,
      ),
    ).toBe(true);
    expect(result.messages.some((message) => message.getType() === "tool")).toBe(true);
  });

  it("replays failed initial tools as marked human evidence with the compacted output", async () => {
    const llm = new ScriptedLlm([new AIMessage("done")]);
    const failingTool = tool(
      async () => {
        throw new Error("no rows");
      },
      {
        name: "get_fundamentals",
        description: "test tool",
        schema: z.object({}),
      },
    );

    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [failingTool],
      systemMessage: "system",
      initialMessages: [new HumanMessage("initial")],
      initialToolCalls: [{ name: "get_fundamentals", args: {} }],
    });

    const firstTurn = llm.seenMessages[0] ?? [];
    expect(
      firstTurn.some(
        (message) =>
          message.getType() === "human" &&
          String(message.content).includes("runtime-provided initial tool evidence") &&
          String(message.content).includes("tool_name=get_fundamentals") &&
          String(message.content).includes("call_id=initial_tool_1") &&
          String(message.content).includes("Tool 'get_fundamentals' raised: no rows"),
      ),
    ).toBe(true);
    expect(firstTurn.some((message) => message.getType() === "tool")).toBe(false);
    expect(
      result.messages.some(
        (message) => message.getType() === "tool" && String(message.content).includes("no rows"),
      ),
    ).toBe(true);
  });

  it.each([
    "get_fundamentals",
    "get_rke_research_context",
  ])("limits %s executions to three without charging initial calls", async (toolName) => {
    vi.stubEnv("MOSAIC_RKE_ENABLED", "1");
    const llm = new ScriptedLlm([
      new AIMessage({
        content: "",
        tool_calls: [1, 2, 3, 4].map((value) => ({
          id: `c${value}`,
          name: toolName,
          args: { value },
          type: "tool_call" as const,
        })),
      }),
      new AIMessage("budget-aware analysis"),
    ]);
    const executed: number[] = [];
    const getFundamentals = tool(
      async ({ value }) => {
        executed.push(value);
        return `result:${value}`;
      },
      {
        name: toolName,
        description: "test tool",
        schema: z.object({ value: z.number() }),
      },
    );

    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [getFundamentals],
      systemMessage: "system",
      initialMessages: [new HumanMessage("initial")],
      initialToolCalls: [{ name: toolName, args: { value: 0 } }],
      maxLoops: 3,
    });

    expect(result.analysisText).toBe("budget-aware analysis");
    expect(executed).toEqual([0, 1, 2, 3]);
    expect(result.toolCalls).toBe(5);
    expect(result.toolExecutions).toBe(4);
    expect(result.toolStatuses).toHaveLength(5);
    expect(result.toolStatuses.at(-1)?.dispatched).toBe(false);
    if (toolName === "get_rke_research_context") {
      expect(result.toolStatuses.at(-1)?.rke_outcome).toBe("budget_not_executed");
    }
    expect(result.toolStatuses.at(-1)).toEqual(
      expect.objectContaining({ call_id: "c4", failed: true, cache_hit: false }),
    );
    expect(
      result.messages
        .filter((message) => message.getType() === "tool")
        .map((message) => String(message.content)),
    ).toEqual([
      "result:0",
      "result:1",
      "result:2",
      "result:3",
      expect.stringContaining("model-selected tool-call budget exhausted"),
    ]);
    expect(String(llm.seenMessages[0]?.[0]?.content)).toContain(
      "at most 3 model-selected tool calls",
    );
    expect(String(llm.seenMessages[1]?.[0]?.content)).toContain("remaining budget is 0");
  });

  it.each([
    ["available", "## RKE research context for macro.china\n\n### Research case FCRED-1"],
    [
      "normal_empty",
      "## RKE research context for macro.dollar\n\nNo matching RKE context was available for this agent/request.",
    ],
    ["returned_unclassified", "unexpected reply"],
    ["returned_unclassified", "## RKE research context for macro.china\n\n### Prior rke-1"],
    [
      "returned_unclassified",
      "## RKE research context for macro.china\n\n### Research case FCRED-1\n\nNo matching RKE context was available for this agent/request.",
    ],
    [
      "authorization_rejected",
      new RpcError("tools.call", INVALID_PARAMS, "authority missing", {
        category: "authorization_rejected",
        reason_code: "KNOT_TOOL_AUTHORITY_MISSING",
      }),
    ],
    ["request_rejected", new RpcError("tools.call", INVALID_PARAMS, "invalid arguments")],
    [
      "blocked",
      new RpcError("tools.call", -32001, "preflight failed", {
        reason_code: "RKE_CONTEXT_PREFLIGHT_FAILED",
      }),
    ],
    ["execution_failed", new Error("transport unavailable")],
  ])("records actual RKE outcome %s without counting cached replies as dispatches", async (outcome, response) => {
    vi.stubEnv("MOSAIC_RKE_ENABLED", "1");
    const call = {
      id: "first",
      name: "get_rke_research_context",
      args: {},
      type: "tool_call" as const,
    };
    const llm = new ScriptedLlm([
      new AIMessage({ content: "", tool_calls: [call] }),
      new AIMessage({ content: "", tool_calls: [{ ...call, id: "cached" }] }),
      new AIMessage("done"),
    ]);
    const logs: string[] = [];
    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [
        tool(
          async () => {
            if (response instanceof Error) throw response;
            return response;
          },
          { name: call.name, description: "test", schema: z.object({}) },
        ),
      ],
      systemMessage: "system",
      initialMessages: [],
      onLog: (message) => logs.push(message),
    });
    expect(result.toolStatuses).toMatchObject([
      { rke_outcome: outcome, dispatched: true, cache_hit: false },
      { rke_outcome: outcome, dispatched: false, cache_hit: true },
    ]);
    expect(logs.filter((line) => line === "rke_dispatch")).toHaveLength(1);
    expect(logs.filter((line) => line.startsWith("rke_call "))).toEqual([
      `rke_call outcome=${outcome} cache_hit=0`,
      `rke_call outcome=${outcome} cache_hit=1`,
    ]);
  });

  it.each([false, true])("reserves an RKE slot across batches: split=%s", async (split) => {
    vi.stubEnv("MOSAIC_RKE_ENABLED", "1");
    const otherCalls = [1, 2, 3].map((value) => ({
      id: `other-${value}`,
      name: "get_other",
      args: { value },
      type: "tool_call" as const,
    }));
    const rkeCall = {
      id: "rke",
      name: "get_rke_research_context",
      args: {},
      type: "tool_call" as const,
    };
    const llm = new ScriptedLlm([
      ...(split
        ? [
            new AIMessage({ content: "", tool_calls: otherCalls }),
            new AIMessage({ content: "", tool_calls: [rkeCall] }),
          ]
        : [new AIMessage({ content: "", tool_calls: [...otherCalls, rkeCall] })]),
      new AIMessage("done"),
    ]);
    const executed: string[] = [];
    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [
        tool(
          async ({ value }) => {
            executed.push(`other-${value}`);
            return "ok";
          },
          { name: "get_other", description: "test", schema: z.object({ value: z.number() }) },
        ),
        tool(
          async () => {
            executed.push("rke");
            return "ok";
          },
          { name: "get_rke_research_context", description: "test", schema: z.object({}) },
        ),
      ],
      reserveRkeQuery: true,
      systemMessage: "system",
      initialMessages: [],
    });
    expect(executed).toEqual(["other-1", "other-2", "rke"]);
    expect(result.toolExecutions).toBe(3);
    expect(result.toolStatuses.find((status) => status.call_id === "other-3")?.failed).toBe(true);
    expect(String(llm.seenMessages[0]?.[0]?.content)).toContain(
      "reserved for get_rke_research_context",
    );
  });

  it.each([
    false,
    true,
  ])("releases the reservation after an initial RKE attempt: failed=%s", async (failed) => {
    vi.stubEnv("MOSAIC_RKE_ENABLED", "1");
    const llm = new ScriptedLlm([
      new AIMessage({
        content: "",
        tool_calls: [1, 2, 3].map((value) => ({
          id: `other-${value}`,
          name: "get_other",
          args: { value },
          type: "tool_call" as const,
        })),
      }),
      new AIMessage("done"),
    ]);
    const executed: number[] = [];
    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [
        tool(
          async ({ value }) => {
            executed.push(value);
            return "ok";
          },
          { name: "get_other", description: "test", schema: z.object({ value: z.number() }) },
        ),
        tool(
          async () => {
            if (failed) throw new Error("unavailable");
            return "ok";
          },
          { name: "get_rke_research_context", description: "test", schema: z.object({}) },
        ),
      ],
      initialToolCalls: [{ name: "get_rke_research_context", args: {} }],
      reserveRkeQuery: true,
      systemMessage: "system",
      initialMessages: [],
    });
    expect(executed).toEqual([1, 2, 3]);
    expect(result.toolExecutions).toBe(4);
    expect(String(llm.seenMessages[0]?.[0]?.content)).not.toContain("reserved for");
  });

  it("uses the runtime-only initial bridge invocation before normal tool validation", async () => {
    const llm = new ScriptedLlm([new AIMessage("done")]);
    let normalCalls = 0;
    let initialCalls = 0;
    const requiredArgsTool = tool(
      async ({ ticker }) => {
        normalCalls++;
        return `normal:${ticker}`;
      },
      {
        name: "get_fundamentals",
        description: "test tool",
        schema: z.object({ ticker: z.string() }),
      },
    );
    Object.defineProperty(requiredArgsTool, BRIDGE_INITIAL_TOOL_INVOKE, {
      value: async () => {
        initialCalls++;
        return "frozen-initial";
      },
    });

    const result = await runAgentToolLoop({
      llm: llm as never,
      tools: [requiredArgsTool],
      systemMessage: "system",
      initialMessages: [new HumanMessage("initial")],
      initialToolCalls: [{ name: "get_fundamentals", args: {} }],
    });

    expect(result.analysisText).toBe("done");
    expect(initialCalls).toBe(1);
    expect(normalCalls).toBe(0);
    const firstTurn = llm.seenMessages[0] ?? [];
    expect(
      firstTurn.some(
        (message) =>
          message.getType() === "human" &&
          String(message.content).includes("runtime-provided initial tool evidence") &&
          String(message.content).includes("tool_name=get_fundamentals") &&
          String(message.content).includes("call_id=initial_tool_1") &&
          String(message.content).includes("frozen-initial"),
      ),
    ).toBe(true);
    expect(firstTurn.some((message) => message.getType() === "tool")).toBe(false);
    expect(
      result.messages.some(
        (message) =>
          message.getType() === "ai" && ((message as AIMessage).tool_calls ?? []).length > 0,
      ),
    ).toBe(true);
    expect(result.messages.some((message) => message.getType() === "tool")).toBe(true);
  });
});
