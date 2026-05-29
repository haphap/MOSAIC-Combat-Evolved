import type { BaseMessage } from "@langchain/core/messages";
import { AIMessage, HumanMessage } from "@langchain/core/messages";
import { tool } from "@langchain/core/tools";
import { describe, expect, it } from "vitest";
import { z } from "zod";
import {
  runToolReportChain,
  type SystemMessagePhase,
  TOOL_RECOVERY_DATA_UNAVAILABLE_PREFIX,
} from "../src/agents/helpers/tool_report_chain.js";

/**
 * Programmable mock LLM. Caller pushes scripted AIMessages; each ``invoke``
 * pops the next response. Tracks whether ``bindTools`` was used so tests can
 * assert the chain bound (or skipped binding) tools per phase.
 */
class ScriptedLlm {
  invokeCalls: BaseMessage[][] = [];
  bindToolsCalled = 0;
  private readonly responses: AIMessage[];

  constructor(responses: AIMessage[]) {
    this.responses = [...responses];
  }

  bindTools(_tools: unknown): ScriptedLlm {
    this.bindToolsCalled += 1;
    return this;
  }

  async invoke(messages: BaseMessage[]): Promise<AIMessage> {
    this.invokeCalls.push(messages);
    const next = this.responses.shift();
    if (!next) throw new Error("ScriptedLlm exhausted");
    return next;
  }
}

const SIMPLE_SYSTEM_BUILDER = (phase: SystemMessagePhase): string => {
  switch (phase.kind) {
    case "main":
      return "system: main";
    case "fallback":
      return "system: fallback";
    case "recovery":
      return `system: recovery\n\n${phase.recoveryContext}`;
  }
};

describe("runToolReportChain", () => {
  it("returns empty report when the LLM emits tool_calls (graph routes to ToolNode)", async () => {
    const llm = new ScriptedLlm([
      new AIMessage({
        content: "",
        tool_calls: [{ id: "c1", name: "get_x", args: {} }],
      }),
    ]);
    const { result, report } = await runToolReportChain({
      llm: llm as unknown as Parameters<typeof runToolReportChain>[0]["llm"],
      tools: [],
      baseMessages: [new HumanMessage("user msg")],
      buildSystemMessage: SIMPLE_SYSTEM_BUILDER,
      language: "Chinese",
    });
    expect(report).toBe("");
    expect(result.tool_calls?.[0]?.id).toBe("c1");
    expect(llm.invokeCalls.length).toBe(1);
    expect(llm.bindToolsCalled).toBe(1);
  });

  it("accepts a clean report on the first non-tool-call response", async () => {
    const goodReport = "概览段：央行立场偏松。\n\n一、立场\nPBOC 净投放扩大。";
    const llm = new ScriptedLlm([new AIMessage(goodReport)]);
    const { report } = await runToolReportChain({
      llm: llm as unknown as Parameters<typeof runToolReportChain>[0]["llm"],
      tools: [],
      baseMessages: [new HumanMessage("user")],
      buildSystemMessage: SIMPLE_SYSTEM_BUILDER,
      language: "Chinese",
    });
    expect(report).toContain("一、立场");
    expect(llm.invokeCalls.length).toBe(1);
  });

  it("falls back when the first response is process-only narration", async () => {
    const llm = new ScriptedLlm([
      new AIMessage("现在所有数据已经获取完毕，下面开始撰写完整的分析报告。"),
      new AIMessage("一、立场\nPBOC 净投放扩大。"),
    ]);
    const { report } = await runToolReportChain({
      llm: llm as unknown as Parameters<typeof runToolReportChain>[0]["llm"],
      tools: [],
      baseMessages: [new HumanMessage("user")],
      buildSystemMessage: SIMPLE_SYSTEM_BUILDER,
      language: "Chinese",
    });
    expect(report).toContain("一、立场");
    // Two invocations: main (process-only) + fallback (good)
    expect(llm.invokeCalls.length).toBe(2);
  });

  it("returns the last non-empty draft when rejectedReportFallback=last_attempt", async () => {
    const llm = new ScriptedLlm([
      new AIMessage("partial draft"),
      new AIMessage("another partial"),
      new AIMessage("third"),
    ]);
    const { report } = await runToolReportChain({
      llm: llm as unknown as Parameters<typeof runToolReportChain>[0]["llm"],
      tools: [],
      baseMessages: [new HumanMessage("user")],
      buildSystemMessage: SIMPLE_SYSTEM_BUILDER,
      acceptanceCheck: () => false, // every attempt rejected
      rejectedReportFallback: "last_attempt",
      language: "English",
    });
    expect(report).toBe("third");
    // main + fallback + nudge = 3 invocations
    expect(llm.invokeCalls.length).toBe(3);
  });

  it("returns empty report when every attempt fails and policy is 'empty'", async () => {
    const llm = new ScriptedLlm([new AIMessage("a"), new AIMessage("b"), new AIMessage("c")]);
    const { report } = await runToolReportChain({
      llm: llm as unknown as Parameters<typeof runToolReportChain>[0]["llm"],
      tools: [],
      baseMessages: [new HumanMessage("user")],
      buildSystemMessage: SIMPLE_SYSTEM_BUILDER,
      acceptanceCheck: () => false,
      rejectedReportFallback: "empty",
      language: "English",
    });
    expect(report).toBe("");
  });

  it("triggers unexecuted-tool-recovery when intent is detected and replays with tool data", async () => {
    let pbocCalls = 0;
    const pbocTool = tool(
      async () => {
        pbocCalls += 1;
        return "trade_date,op_type,volume\n20240624,Reverse Repo,200";
      },
      {
        name: "get_pboc_ops",
        description: "fake PBOC OMO",
        schema: z.object({ curr_date: z.string() }),
      },
    );

    const llm = new ScriptedLlm([
      // First response describes a future tool call but does NOT execute it
      new AIMessage("好的，接下来我将调用 get_pboc_ops 获取央行操作数据，然后展开分析。"),
      // After recovery payload runs, replay produces a real report
      new AIMessage("一、立场\nPBOC 本周净投放 200 亿（reverse repo），立场偏松。"),
    ]);

    const { report } = await runToolReportChain({
      llm: llm as unknown as Parameters<typeof runToolReportChain>[0]["llm"],
      tools: [pbocTool],
      baseMessages: [new HumanMessage("2024-06-24")],
      buildSystemMessage: SIMPLE_SYSTEM_BUILDER,
      unexecutedToolRecovery: {
        triggerToolNames: ["get_pboc_ops"],
        toolPayloads: [{ tool: pbocTool, payload: { curr_date: "2024-06-24" } }],
      },
      language: "Chinese",
    });

    expect(pbocCalls).toBe(1); // recovery actually ran the tool
    expect(report).toContain("一、立场");
  });

  it("emits the data-unavailable marker when every recovery tool fails", async () => {
    const failingTool = tool(
      async () => {
        throw new Error("tushare token missing");
      },
      {
        name: "get_pboc_ops",
        description: "fake",
        schema: z.object({ curr_date: z.string() }),
      },
    );
    const llm = new ScriptedLlm([
      new AIMessage("好的，接下来我将调用 get_pboc_ops 获取央行操作数据。"),
    ]);

    const { report } = await runToolReportChain({
      llm: llm as unknown as Parameters<typeof runToolReportChain>[0]["llm"],
      tools: [failingTool],
      baseMessages: [new HumanMessage("2024-06-24")],
      buildSystemMessage: SIMPLE_SYSTEM_BUILDER,
      unexecutedToolRecovery: {
        triggerToolNames: ["get_pboc_ops"],
        toolPayloads: [{ tool: failingTool, payload: { curr_date: "2024-06-24" } }],
      },
      language: "Chinese",
    });
    expect(report.startsWith(TOOL_RECOVERY_DATA_UNAVAILABLE_PREFIX)).toBe(true);
    expect(report).toContain("tushare token missing");
    // Only the first invocation ran — recovery short-circuited, no replay
    expect(llm.invokeCalls.length).toBe(1);
  });
});
