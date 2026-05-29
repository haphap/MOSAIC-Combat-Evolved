import { describe, expect, it } from "vitest";
import { containsCjk, extractTextContent } from "../src/agents/helpers/content.js";
import {
  isProcessOnlyReportText,
  isToolCallText,
  looksLikeProcessNarration,
  looksLikeUnexecutedToolIntent,
  stripProcessOnlyReportPrefix,
} from "../src/agents/helpers/process_narration.js";

describe("extractTextContent", () => {
  it("returns plain string content unchanged (trimmed)", () => {
    expect(extractTextContent("  hello  ")).toBe("hello");
  });

  it("joins string array entries with newlines", () => {
    expect(extractTextContent(["a", "b"])).toBe("a\nb");
  });

  it("extracts text from anthropic-style content blocks", () => {
    const blocks = [
      { type: "text", text: "first part" },
      { type: "text", text: "second part" },
    ];
    expect(extractTextContent(blocks)).toBe("first part\nsecond part");
  });

  it("recurses into nested .content fields", () => {
    const nested = { type: "anything", content: [{ type: "text", text: "deep" }] };
    expect(extractTextContent(nested)).toBe("deep");
  });

  it("ignores non-text blocks like tool_use", () => {
    const blocks = [
      { type: "tool_use", text: "should be ignored", input: {} },
      { type: "text", text: "kept" },
    ];
    expect(extractTextContent(blocks)).toBe("kept");
  });

  it("returns empty string for null / undefined", () => {
    expect(extractTextContent(null)).toBe("");
    expect(extractTextContent(undefined)).toBe("");
  });
});

describe("containsCjk", () => {
  it("detects Chinese characters", () => {
    expect(containsCjk("货币政策")).toBe(true);
    expect(containsCjk("plain ascii")).toBe(false);
    expect(containsCjk("")).toBe(false);
  });
});

describe("looksLikeProcessNarration", () => {
  it("matches Chinese 'data ready, now I will write' opening lines", () => {
    expect(looksLikeProcessNarration("数据已经全部获取完毕，现在我来撰写分析报告。")).toBe(true);
    expect(looksLikeProcessNarration("以下是央行操作的分析报告：")).toBe(true);
    expect(looksLikeProcessNarration("报告已就绪，下面给出完整结论。")).toBe(true);
  });

  it("does not match real opening sentences", () => {
    expect(
      looksLikeProcessNarration(
        "央行立场维持中性偏松，本周净投放2000亿，MLF缩量1500亿但利率小幅下行。",
      ),
    ).toBe(false);
    expect(looksLikeProcessNarration("")).toBe(false);
  });
});

describe("isToolCallText", () => {
  it("flags XML-formatted tool calls in any case", () => {
    expect(isToolCallText("<tool_call>get_pboc_ops</tool_call>")).toBe(true);
    expect(isToolCallText("<function=foo>x</function>")).toBe(true);
    expect(isToolCallText("<FUNCTION_CALL>...</FUNCTION_CALL>")).toBe(true);
  });

  it("does not flag normal report text", () => {
    expect(isToolCallText("一、央行立场与公开市场操作")).toBe(false);
  });
});

describe("isProcessOnlyReportText", () => {
  it("flags short Chinese 'now I will write' notes", () => {
    expect(isProcessOnlyReportText("现在所有数据已经获取完毕，下面开始撰写完整的分析报告。")).toBe(
      true,
    );
  });

  it("flags short English 'now let me write the report' notes", () => {
    // EN_DATA_READY_RE requires explicit phrasing like "retrieved data" /
    // "gathered information" / "data is ready" — generic "based on the data"
    // does not qualify, mirroring the Python contract.
    expect(
      isProcessOnlyReportText(
        "Now let me write the complete analysis report based on retrieved data.",
      ),
    ).toBe(true);
  });

  it("does not flag a real report once a 一、 heading is present", () => {
    const real = "现在我来撰写报告：\n\n一、央行立场\n PBOC 维持中性偏松。";
    expect(isProcessOnlyReportText(real)).toBe(false);
  });

  it("ignores text longer than 700 chars", () => {
    const long = "数据已经获取，现在开始撰写报告。".repeat(100);
    expect(isProcessOnlyReportText(long)).toBe(false);
  });
});

describe("stripProcessOnlyReportPrefix", () => {
  it("removes a process line that occupies its own paragraph", () => {
    const text =
      "现在所有数据已经获取完毕，下面开始撰写完整的分析报告。\n\n一、央行立场\nPBOC 中性偏松。";
    const out = stripProcessOnlyReportPrefix(text);
    expect(out.startsWith("一、央行立场")).toBe(true);
  });

  it("leaves clean text untouched", () => {
    expect(stripProcessOnlyReportPrefix("PBOC 本周净投放 2000 亿，MLF 缩量。")).toBe(
      "PBOC 本周净投放 2000 亿，MLF 缩量。",
    );
  });
});

describe("looksLikeUnexecutedToolIntent", () => {
  it("flags 'I will call get_pboc_ops' intent without execution", () => {
    expect(
      looksLikeUnexecutedToolIntent(
        "好的，接下来我将调用 get_pboc_ops 获取央行公开市场操作数据。",
        "get_pboc_ops",
      ),
    ).toBe(true);
    expect(
      looksLikeUnexecutedToolIntent(
        "我准备使用 get_yield_curve_cn 拉取国债收益率曲线。",
        "get_yield_curve_cn",
      ),
    ).toBe(true);
  });

  it("does not flag text inside a finished report (heading present)", () => {
    const finished = "一、央行立场\nget_pboc_ops 返回的本周净投放为 2000 亿，立场偏松。";
    expect(looksLikeUnexecutedToolIntent(finished, "get_pboc_ops")).toBe(false);
  });

  it("returns false for missing tool name or empty text", () => {
    expect(looksLikeUnexecutedToolIntent("", "anything")).toBe(false);
    expect(looksLikeUnexecutedToolIntent("text", "")).toBe(false);
  });
});
