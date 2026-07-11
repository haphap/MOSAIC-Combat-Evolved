import { afterEach, describe, expect, it } from "vitest";
import type { MosaicConfig } from "../src/bridge/types.js";
import { createLlmFromConfig } from "../src/llm/factory.js";

const ENV_KEYS = [
  "MOSAIC_RKE_VLLM_BASE_URL",
  "MOSAIC_VLLM_API_KEY",
  "OPENAI_API_KEY",
  "VLLM_BASE_URL",
] as const;

const savedEnv = Object.fromEntries(ENV_KEYS.map((key) => [key, process.env[key]]));

describe("createLlmFromConfig", () => {
  afterEach(() => {
    for (const key of ENV_KEYS) {
      const value = savedEnv[key];
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }
  });

  it("uses the RKE vLLM base URL fallback", () => {
    delete process.env.VLLM_BASE_URL;
    process.env.MOSAIC_RKE_VLLM_BASE_URL = "https://example.invalid/v1";

    const handle = createLlmFromConfig(config());

    expect(handle.provider).toBe("vllm");
    expect(handle.baseUrl).toBe("https://example.invalid/v1");
  });

  it("keeps local vLLM usable without an API key", () => {
    delete process.env.MOSAIC_RKE_VLLM_BASE_URL;
    delete process.env.MOSAIC_VLLM_API_KEY;
    delete process.env.OPENAI_API_KEY;
    delete process.env.VLLM_BASE_URL;

    const handle = createLlmFromConfig(config());

    expect(handle.provider).toBe("vllm");
    expect(handle.baseUrl).toBe("http://localhost:8000/v1");
  });

  it("disables Qwen thinking output for vLLM requests", () => {
    const handle = createLlmFromConfig(config());
    const params = (
      handle.llm as unknown as { invocationParams: () => Record<string, unknown> }
    ).invocationParams();

    expect(params.chat_template_kwargs).toEqual({ enable_thinking: false });
  });
});

function config(): MosaicConfig {
  return {
    llm_provider: "vllm",
    deep_think_llm: "test-model",
    quick_think_llm: "test-model",
    backend_url: null,
    anthropic_base_url: null,
    anthropic_effort: null,
  } as MosaicConfig;
}
