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
  toolCallFingerprint,
} from "../src/agents/helpers/agent_loop.js";

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

  it("serves repeated same-args tool calls from the per-agent cache", async () => {
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
        return `result-${executions}`;
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
    expect(
      result.messages
        .filter((message) => message.getType() === "tool")
        .map((message) => String(message.content)),
    ).toEqual(["result-1", "result-1"]);
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
});
