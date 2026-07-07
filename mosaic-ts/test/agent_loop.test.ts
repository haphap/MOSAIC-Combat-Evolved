import { AIMessage, HumanMessage, ToolMessage } from "@langchain/core/messages";
import { describe, expect, it } from "vitest";
import {
  compactToolOutput,
  parseToolOutputMaxChars,
  pruneConsumedToolHistory,
  resolveToolOutputMaxChars,
  toolCallFingerprint,
} from "../src/agents/helpers/agent_loop.js";

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

  it("drops consumed tool-call exchanges from the replay history", () => {
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
        content: "x".repeat(100_000),
        tool_call_id: "c1",
      }),
      new AIMessage("next step"),
    ]);

    expect(pruned.map((message) => message.getType())).toEqual(["human", "ai", "human", "ai"]);
    expect(String(pruned[1]?.content)).toBe("retain this short conclusion");
    expect(String(pruned[2]?.content)).toContain("Prior tool results retained");
    expect(String(pruned[2]?.content)).toContain("get_big_table#");
    expect(String(pruned[2]?.content)).toContain("prior_tool_output_compacted");
    expect(String(pruned[2]?.content)).not.toContain("x".repeat(1_000));
  });

  it("builds stable short tool-call fingerprints from canonical args", () => {
    expect(toolCallFingerprint("get_x", { b: 2, a: 1 })).toBe(
      toolCallFingerprint("get_x", { a: 1, b: 2 }),
    );
    expect(toolCallFingerprint("get_x", { a: 1 })).not.toBe(toolCallFingerprint("get_x", { a: 2 }));
  });
});
