/**
 * Regression: when MAX_LOOPS is reached, the forced final answer MUST come
 * from the unbound LLM (no tools attached). Otherwise the model can ignore
 * the "do not call tools" instruction in the prompt and keep emitting
 * tool_calls forever — a real correctness bug, not a stylistic concern.
 */

import { AIMessage, type BaseMessage, HumanMessage, SystemMessage } from "@langchain/core/messages";
import { tool } from "@langchain/core/tools";
import { describe, expect, it } from "vitest";
import { z } from "zod";
import { runToolLoop } from "../src/cli/commands/tool-loop.js";

interface FakeLlm {
  calls: number;
  invoke: (messages: BaseMessage[]) => Promise<AIMessage>;
}

/** A bound LLM that ALWAYS asks to call the tool with `{n: <call-counter>}`. */
function makeAlwaysToolCallingLlm(toolName: string): FakeLlm {
  let n = 0;
  const llm: FakeLlm = {
    calls: 0,
    async invoke(_messages: BaseMessage[]): Promise<AIMessage> {
      llm.calls++;
      n++;
      return new AIMessage({
        content: "",
        tool_calls: [{ id: `c${n}`, name: toolName, args: { n }, type: "tool_call" }],
      });
    },
  };
  return llm;
}

/** An unbound LLM that returns a plain text answer. */
function makePlainAnswerLlm(answer: string): FakeLlm {
  const llm: FakeLlm = {
    calls: 0,
    async invoke(_messages: BaseMessage[]): Promise<AIMessage> {
      llm.calls++;
      return new AIMessage({ content: answer });
    },
  };
  return llm;
}

const noopTool = tool(async ({ n }) => `tool result ${n}`, {
  name: "noop_tool",
  description: "test stub",
  schema: z.object({ n: z.int() }),
});

describe("runToolLoop", () => {
  it("returns the AI message immediately when no tool_calls are emitted", async () => {
    const messages: BaseMessage[] = [new SystemMessage("system"), new HumanMessage("hi")];
    const direct = makePlainAnswerLlm("hello!");
    const unbound = makePlainAnswerLlm("UNREACHABLE");

    const result = await runToolLoop(messages, direct, unbound, [noopTool], 6);

    expect(result.content).toBe("hello!");
    expect(direct.calls).toBe(1);
    expect(unbound.calls).toBe(0);
  });

  it("forces a final answer from the UNBOUND llm when maxLoops is hit", async () => {
    const messages: BaseMessage[] = [new SystemMessage("system"), new HumanMessage("hi")];
    const bound = makeAlwaysToolCallingLlm("noop_tool");
    const unbound = makePlainAnswerLlm("forced final answer");

    const result = await runToolLoop(messages, bound, unbound, [noopTool], 3);

    expect(result.content).toBe("forced final answer");
    // Bound LLM was invoked once per loop iteration (maxLoops times).
    expect(bound.calls).toBe(3);
    // Unbound LLM was invoked exactly once for the forced final answer.
    expect(unbound.calls).toBe(1);
  });

  it("appends a Tool message with the tool output for each emitted tool_call", async () => {
    const messages: BaseMessage[] = [new SystemMessage("system"), new HumanMessage("hi")];
    const bound = makeAlwaysToolCallingLlm("noop_tool");
    const unbound = makePlainAnswerLlm("done");

    await runToolLoop(messages, bound, unbound, [noopTool], 2);

    // Original 2 + 2 (AI w/ tool_call) + 2 (Tool replies) = 6.
    expect(messages.length).toBe(6);
    // ToolMessage contents follow the n=1, n=2 progression.
    const toolMessages = messages.filter((m) => m.getType() === "tool");
    expect(toolMessages.map((m) => m.content)).toEqual(["tool result 1", "tool result 2"]);
  });

  it("substitutes a stub message when the LLM names an unknown tool", async () => {
    const messages: BaseMessage[] = [new SystemMessage("system"), new HumanMessage("hi")];
    const bound = makeAlwaysToolCallingLlm("missing_tool");
    const unbound = makePlainAnswerLlm("done");

    await runToolLoop(messages, bound, unbound, [noopTool], 1);

    const toolMessages = messages.filter((m) => m.getType() === "tool");
    expect(toolMessages).toHaveLength(1);
    expect(toolMessages[0]?.content).toMatch(/not available/);
  });
});
