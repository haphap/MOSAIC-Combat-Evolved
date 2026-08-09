import { AIMessage, type BaseMessage, HumanMessage, ToolMessage } from "@langchain/core/messages";
import { tool } from "@langchain/core/tools";
import { describe, expect, it } from "vitest";
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
import { type BridgeApi, bridgeToolFromMetadata } from "../src/bridge/index.js";
import { BRIDGE_INITIAL_TOOL_INVOKE } from "../src/bridge/tools.js";

class ScriptedLlm {
  bindToolsCalled = 0;
  readonly seenMessages: BaseMessage[][] = [];

  constructor(private readonly responses: AIMessage[]) {}

  bindTools(): ScriptedLlm {
    this.bindToolsCalled++;
    return this;
  }

  async invoke(messages: BaseMessage[]): Promise<AIMessage> {
    this.seenMessages.push(messages);
    const next = this.responses.shift();
    if (!next) throw new Error("script exhausted");
    return next;
  }
}

describe("agent tool loop helpers", () => {
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
    expect(
      llm.seenMessages[0]?.some(
        (message) => message.getType() === "tool" && String(message.content).includes("600519.SH"),
      ),
    ).toBe(true);
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
    expect(
      llm.seenMessages[0]?.some(
        (message) =>
          message.getType() === "tool" && String(message.content).includes("frozen-initial"),
      ),
    ).toBe(true);
  });
});
