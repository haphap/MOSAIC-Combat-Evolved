import { AIMessage, HumanMessage, SystemMessage } from "@langchain/core/messages";
import { describe, expect, it } from "vitest";
import { z } from "zod";
import {
  bindStructured,
  buildProseOnlyFallbackPrompt,
  buildStructuredOutputPrompt,
  invokeStructuredOrFreetext,
  stripStructuredOnlyText,
} from "../src/agents/helpers/structured_output.js";

/**
 * Programmable mock LLM. Tracks invoke calls + supports
 * ``withStructuredOutput`` toggling so we can simulate providers that don't
 * implement structured output.
 */
class ScriptedLlm {
  invokeCalls: SystemMessage[][] = [];
  structuredCalls = 0;
  readonly supportsStructured: boolean;
  readonly structuredResponse: unknown;
  readonly structuredThrows: Error | null;
  private readonly responses: AIMessage[];

  constructor(
    opts: {
      responses?: AIMessage[];
      supportsStructured?: boolean;
      structuredResponse?: unknown;
      structuredThrows?: Error | null;
    } = {},
  ) {
    this.responses = [...(opts.responses ?? [])];
    this.supportsStructured = opts.supportsStructured ?? true;
    this.structuredResponse = opts.structuredResponse ?? null;
    this.structuredThrows = opts.structuredThrows ?? null;
  }

  withStructuredOutput(_schema: unknown): {
    invoke: (input: unknown) => Promise<unknown>;
  } {
    if (!this.supportsStructured) {
      throw new Error("withStructuredOutput not supported");
    }
    return {
      invoke: async (_input) => {
        this.structuredCalls += 1;
        if (this.structuredThrows) throw this.structuredThrows;
        return this.structuredResponse;
      },
    };
  }

  async invoke(messages: SystemMessage[]): Promise<AIMessage> {
    this.invokeCalls.push(messages);
    const next = this.responses.shift();
    if (!next) throw new Error("ScriptedLlm exhausted");
    return next;
  }
}

const FAKE_LLM = (opts: ConstructorParameters<typeof ScriptedLlm>[0] = {}) =>
  new ScriptedLlm(opts) as unknown as Parameters<typeof bindStructured>[0];

// ============================================================ unit primitives

describe("stripStructuredOnlyText", () => {
  it("returns input unchanged when no sentences are passed", () => {
    expect(stripStructuredOnlyText("system prompt body", [])).toBe("system prompt body");
  });

  it("strips agent-specific structured-only sentences", () => {
    const text =
      "Role description.\n\n" +
      "Populate fields target_weight + add_triggers when supported.\n\n" +
      "Other rules apply.";
    const result = stripStructuredOnlyText(text, [
      "Populate fields target_weight + add_triggers when supported.",
    ]);
    expect(result).not.toContain("target_weight");
    expect(result).toContain("Role description.");
    expect(result).toContain("Other rules apply.");
  });

  it("collapses extra whitespace produced by stripping", () => {
    const text = "alpha\n\n\nbeta\n\n\ngamma";
    expect(stripStructuredOnlyText(text)).toBe("alpha\n\nbeta\n\ngamma");
  });
});

describe("buildStructuredOutputPrompt", () => {
  it("emits an English schema-only prompt for English mode", () => {
    const [system, user] = buildStructuredOutputPrompt(
      "CentralBankSchema",
      ["stance", "key_rate_change_bps"],
      "<irrelevant>",
      "raw evidence text",
      "English",
    );
    expect(system.content).toContain("CentralBankSchema");
    expect(system.content).toContain("stance, key_rate_change_bps");
    expect(system.content).not.toContain("Chinese");
    expect(user.content).toContain("raw evidence text");
  });

  it("appends a Chinese-language clause when language is Chinese", () => {
    const [system, _user] = buildStructuredOutputPrompt(
      "CentralBankSchema",
      ["stance"],
      "",
      "evidence",
      "Chinese",
    );
    expect(system.content).toContain("Chinese");
    expect(system.content).toContain("时机");
  });
});

describe("buildProseOnlyFallbackPrompt", () => {
  it("strips caller-supplied sentences and appends an extra instruction", () => {
    const out = buildProseOnlyFallbackPrompt(
      "Role description.\n\nFIELD-ONLY.",
      "Free text only please.",
      ["FIELD-ONLY."],
    );
    expect(out).toContain("Role description.");
    expect(out).not.toContain("FIELD-ONLY.");
    expect(out).toContain("Free text only please.");
  });
});

// ============================================================ orchestrator

describe("invokeStructuredOrFreetext", () => {
  const Schema = z.object({
    stance: z.enum(["ACCOMMODATIVE", "NEUTRAL", "TIGHTENING"]),
    key_rate_change_bps: z.number(),
  });

  const baseMessages: [SystemMessage, HumanMessage] = [
    new SystemMessage("Analyst role.\n\nFIELD-ONLY-RULE."),
    new HumanMessage("Evidence body"),
  ];

  it("returns structured payload + rendered prose on success", async () => {
    const llm = new ScriptedLlm({
      structuredResponse: { stance: "NEUTRAL", key_rate_change_bps: 0 },
    });
    const result = await invokeStructuredOrFreetext({
      llm: llm as unknown as Parameters<typeof invokeStructuredOrFreetext>[0]["llm"],
      schema: Schema,
      messages: baseMessages,
      render: (r) => `stance=${r.stance}, bps=${r.key_rate_change_bps}`,
      agentName: "central_bank",
    });
    expect(result.structured).toEqual({ stance: "NEUTRAL", key_rate_change_bps: 0 });
    expect(result.rendered).toBe("stance=NEUTRAL, bps=0");
    expect(llm.structuredCalls).toBe(1);
    expect(llm.invokeCalls.length).toBe(0); // free-text path not used
  });

  it("falls back to free text when withStructuredOutput throws at construction", async () => {
    const llm = new ScriptedLlm({
      supportsStructured: false,
      responses: [new AIMessage("PBOC stance: NEUTRAL.")],
    });
    const result = await invokeStructuredOrFreetext({
      llm: llm as unknown as Parameters<typeof invokeStructuredOrFreetext>[0]["llm"],
      schema: Schema,
      messages: baseMessages,
      render: () => "UNREACHABLE",
      agentName: "central_bank",
    });
    expect(result.structured).toBeNull();
    expect(result.rendered).toBe("PBOC stance: NEUTRAL.");
    expect(llm.invokeCalls.length).toBe(1);
  });

  it("falls back to free text when structured invoke throws at runtime", async () => {
    const llm = new ScriptedLlm({
      supportsStructured: true,
      structuredThrows: new Error("schema mismatch"),
      responses: [new AIMessage("Free text recovery body.")],
    });
    const result = await invokeStructuredOrFreetext({
      llm: llm as unknown as Parameters<typeof invokeStructuredOrFreetext>[0]["llm"],
      schema: Schema,
      messages: baseMessages,
      render: () => "UNREACHABLE",
      agentName: "central_bank",
      structuredOnlySentences: ["FIELD-ONLY-RULE."],
    });
    expect(result.structured).toBeNull();
    expect(result.rendered).toBe("Free text recovery body.");
    // Verify structuredOnlySentences actually stripped the schema-only line.
    const sentSystem = llm.invokeCalls[0]?.[0]?.content as string;
    expect(sentSystem).toContain("Analyst role.");
    expect(sentSystem).not.toContain("FIELD-ONLY-RULE.");
  });
});

describe("bindStructured null on unsupported provider", () => {
  it("returns null + warns when withStructuredOutput throws", () => {
    const llm = FAKE_LLM({ supportsStructured: false });
    const Schema = z.object({ x: z.string() });
    const bound = bindStructured(llm, Schema, "test_agent");
    expect(bound).toBeNull();
  });

  it("returns a usable handle when the provider supports it", async () => {
    const llm = new ScriptedLlm({
      supportsStructured: true,
      structuredResponse: { x: "ok" },
    });
    const Schema = z.object({ x: z.string() });
    const bound = bindStructured(
      llm as unknown as Parameters<typeof bindStructured>[0],
      Schema,
      "test_agent",
    );
    expect(bound).not.toBeNull();
    if (bound !== null) {
      const result = await bound.invoke({});
      expect(result).toEqual({ x: "ok" });
    }
  });
});
