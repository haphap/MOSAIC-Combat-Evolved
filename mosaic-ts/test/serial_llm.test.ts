import { describe, expect, it } from "vitest";
import type { LlmHandle } from "../src/llm/factory.js";
import { serializeLlmHandle } from "../src/runtime/serial_llm.js";

describe("serialized LLM handle", () => {
  it("keeps base and structured derivative invocations at concurrency one", async () => {
    let active = 0;
    let peak = 0;
    const runnable = {
      async invoke(value: string) {
        active += 1;
        peak = Math.max(peak, active);
        await new Promise((resolve) => setTimeout(resolve, 5));
        active -= 1;
        return value;
      },
      withStructuredOutput() {
        return this;
      },
      bindTools() {
        return this;
      },
    };
    const handle = serializeLlmHandle({
      llm: runnable,
      provider: "vllm",
      model: "qwen",
      baseUrl: "http://127.0.0.1:8000/v1",
    } as unknown as LlmHandle);
    const structured = (
      handle.llm as unknown as {
        withStructuredOutput: () => { invoke: (value: string) => Promise<string> };
      }
    ).withStructuredOutput();

    const values = await Promise.all([
      handle.llm.invoke("a"),
      structured.invoke("b"),
      handle.llm.invoke("c"),
    ]);

    expect(values).toEqual(["a", "b", "c"]);
    expect(peak).toBe(1);
  });
});
