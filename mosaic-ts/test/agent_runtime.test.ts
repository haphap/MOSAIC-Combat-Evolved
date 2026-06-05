import { describe, expect, it } from "vitest";
import {
  AgentTimeoutError,
  formatAgentEvent,
  formatDurationMs,
  parseAgentTimeoutSeconds,
  resolveAgentTimeoutMs,
  summarizeAgentOutput,
  withAgentTimeout,
} from "../src/agents/helpers/runtime.js";

describe("agent runtime helpers", () => {
  it("parses explicit timeout seconds and off aliases", () => {
    expect(parseAgentTimeoutSeconds(undefined)).toBeUndefined();
    expect(parseAgentTimeoutSeconds(" 12.5 ")).toBe(12.5);
    expect(parseAgentTimeoutSeconds("off")).toBe(0);
    expect(resolveAgentTimeoutMs(1.25)).toBe(1250);
    expect(resolveAgentTimeoutMs(0)).toBe(0);
  });

  it("formats compact agent log events", () => {
    expect(formatAgentEvent("done", "L3", "ackman", ["elapsed=1.2s", "picks=3"])).toBe(
      "[agent:done] L3 ackman elapsed=1.2s picks=3",
    );
    expect(formatDurationMs(65_000)).toBe("1m05s");
    expect(formatDurationMs(119_999)).toBe("2m00s");
  });

  it("aborts and rejects when an agent exceeds its timeout", async () => {
    let observedAbort = false;

    await expect(
      withAgentTimeout(
        (signal) =>
          new Promise<string>((_resolve, reject) => {
            signal.addEventListener("abort", () => {
              observedAbort = true;
              reject(signal.reason);
            });
          }),
        5,
        "L1 central_bank",
      ),
    ).rejects.toBeInstanceOf(AgentTimeoutError);

    expect(observedAbort).toBe(true);
  });

  it("summarizes representative agent outputs without long prose", () => {
    expect(
      summarizeAgentOutput({
        agent: "energy",
        longs: [{ ticker: "600000.SH" }],
        shorts: [],
        sector_score: 0.42,
        key_drivers: ["flow"],
        confidence: 0.73,
      }),
    ).toBe("score=0.42 longs=1 shorts=0 conf=0.73 drivers=1");

    expect(
      summarizeAgentOutput({
        agent: "cio",
        portfolio_actions: [{ ticker: "600519.SH" }, { ticker: "688981.SH" }],
        confidence: 0.6,
      }),
    ).toBe("actions=2 conf=0.60");
  });
});
