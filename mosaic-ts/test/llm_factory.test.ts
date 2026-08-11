import { once } from "node:events";
import { createServer } from "node:http";
import { HumanMessage } from "@langchain/core/messages";
import { afterEach, describe, expect, it } from "vitest";
import type { MosaicConfig } from "../src/bridge/types.js";
import { createLlmFromConfig } from "../src/llm/factory.js";

const ENV_KEYS = [
  "MOSAIC_LLM_API_KEY",
  "MOSAIC_LLM_BASE_URL",
  "MOSAIC_LLM_MAX_TOKENS",
  "MOSAIC_LLM_MODEL",
  "MOSAIC_LLM_PROVIDER",
  "MOSAIC_LLM_THINKING_MODE",
  "MOSAIC_LLM_USER_AGENT",
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

  it("builds the generic API provider entirely from Agent env", () => {
    process.env.MOSAIC_LLM_PROVIDER = "api";
    process.env.MOSAIC_LLM_MODEL = "remote-model";
    process.env.MOSAIC_LLM_BASE_URL = "https://gateway.example/zen/go/v1/chat/completions";
    process.env.MOSAIC_LLM_API_KEY = "test-api-key";
    process.env.MOSAIC_LLM_MAX_TOKENS = "65536";

    const handle = createLlmFromConfig(config());
    const llm = handle.llm as unknown as {
      apiKey?: string;
      clientConfig: {
        baseURL?: string;
      };
      invocationParams: () => Record<string, unknown>;
    };

    expect(handle.provider).toBe("api");
    expect(handle.model).toBe("remote-model");
    expect(handle.baseUrl).toBe("https://gateway.example/zen/go/v1");
    expect(llm.apiKey).toBe("test-api-key");
    expect(llm.clientConfig.baseURL).toBe("https://gateway.example/zen/go/v1");
    expect(llm.invocationParams().max_tokens).toBe(65_536);
  });

  it("sends the normalized path, auth, user agent, model, and token cap on the wire", async () => {
    let request:
      | {
          authorization: string | undefined;
          body: Record<string, unknown>;
          url: string | undefined;
          userAgent: string | undefined;
        }
      | undefined;
    const server = createServer((incoming, response) => {
      const chunks: Buffer[] = [];
      incoming.on("data", (chunk: Buffer) => chunks.push(chunk));
      incoming.on("end", () => {
        request = {
          authorization: incoming.headers.authorization,
          body: JSON.parse(Buffer.concat(chunks).toString("utf8")) as Record<string, unknown>,
          url: incoming.url,
          userAgent: incoming.headers["user-agent"],
        };
        response.writeHead(200, { "Content-Type": "application/json" });
        response.end(
          JSON.stringify({
            id: "chatcmpl-test",
            object: "chat.completion",
            created: 0,
            model: "remote-model",
            choices: [
              {
                index: 0,
                finish_reason: "stop",
                message: { role: "assistant", content: "ok" },
              },
            ],
            usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
          }),
        );
      });
    });
    server.listen(0, "127.0.0.1");
    await once(server, "listening");
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("mock API address unavailable");

    try {
      process.env.MOSAIC_LLM_API_KEY = "test-api-key";
      process.env.MOSAIC_LLM_THINKING_MODE = "disabled";
      process.env.MOSAIC_LLM_USER_AGENT = "mosaic-agent-loop-test/9.9";
      const handle = createLlmFromConfig(config(), {
        provider: "api",
        model: "remote-model",
        baseUrl: `http://127.0.0.1:${address.port}/zen/go/v1/chat/completions`,
        maxTokens: 65_536,
      });

      const answer = await handle.llm.invoke([new HumanMessage("hello")]);

      expect(answer.content).toBe("ok");
      expect(request).toMatchObject({
        authorization: "Bearer test-api-key",
        url: "/zen/go/v1/chat/completions",
        body: {
          model: "remote-model",
          max_tokens: 65_536,
          thinking: { type: "disabled" },
        },
      });
      expect(request?.userAgent).toBe("mosaic-agent-loop-test/9.9");
    } finally {
      server.close();
      await once(server, "close");
    }
  });

  it.each([
    "https://gateway.example/zen/go/v1",
    "https://gateway.example/zen/go/v1/",
    "https://gateway.example/zen/go/v1/chat/completions",
    "https://gateway.example/zen/go/v1/chat/completions/",
  ])("normalizes API endpoint form %s", (baseUrl) => {
    process.env.MOSAIC_LLM_API_KEY = "test-api-key";

    const handle = createLlmFromConfig(config(), {
      provider: "api",
      model: "remote-model",
      baseUrl,
    });

    expect(handle.baseUrl).toBe("https://gateway.example/zen/go/v1");
  });

  it("keeps explicit API options above Agent env", () => {
    process.env.MOSAIC_LLM_PROVIDER = "api";
    process.env.MOSAIC_LLM_MODEL = "env-model";
    process.env.MOSAIC_LLM_BASE_URL = "https://env.example/v1";
    process.env.MOSAIC_LLM_API_KEY = "test-api-key";
    process.env.MOSAIC_LLM_MAX_TOKENS = "1024";

    const handle = createLlmFromConfig(config(), {
      provider: "api",
      model: "option-model",
      baseUrl: "https://option.example/v1/chat/completions",
      maxTokens: 2_048,
    });

    expect(handle.model).toBe("option-model");
    expect(handle.baseUrl).toBe("https://option.example/v1");
    expect(
      (
        handle.llm as unknown as { invocationParams: () => Record<string, unknown> }
      ).invocationParams().max_tokens,
    ).toBe(2_048);
  });

  it("fails closed when the generic API endpoint or key is missing", () => {
    delete process.env.MOSAIC_LLM_API_KEY;
    delete process.env.MOSAIC_LLM_BASE_URL;

    expect(() => createLlmFromConfig(config(), { provider: "api", model: "remote-model" })).toThrow(
      "Missing base URL for provider 'api'",
    );

    process.env.MOSAIC_LLM_BASE_URL = "https://gateway.example/v1";
    expect(() => createLlmFromConfig(config(), { provider: "api", model: "remote-model" })).toThrow(
      "Missing API key for provider 'api'",
    );
  });

  it("rejects endpoint credentials because API auth belongs in env", () => {
    process.env.MOSAIC_LLM_API_KEY = "test-api-key";

    expect(() =>
      createLlmFromConfig(config(), {
        provider: "api",
        model: "remote-model",
        baseUrl: "https://embedded-secret@gateway.example/v1",
      }),
    ).toThrow("Invalid base URL for provider 'api'");
  });

  it("rejects invalid Agent max-token env without making a provider", () => {
    process.env.MOSAIC_LLM_MAX_TOKENS = "not-a-number";

    expect(() => createLlmFromConfig(config())).toThrow(
      "MOSAIC_LLM_MAX_TOKENS must be a positive integer",
    );
  });

  it("rejects CR/LF in the custom API user agent", () => {
    process.env.MOSAIC_LLM_API_KEY = "test-api-key";
    process.env.MOSAIC_LLM_USER_AGENT = "mosaic-test\r\ninjected: value";

    expect(() =>
      createLlmFromConfig(config(), {
        provider: "api",
        model: "remote-model",
        baseUrl: "https://gateway.example/v1",
      }),
    ).toThrow("MOSAIC_LLM_USER_AGENT must not contain CR or LF");
  });

  it("rejects an invalid API thinking mode", () => {
    process.env.MOSAIC_LLM_API_KEY = "test-api-key";
    process.env.MOSAIC_LLM_THINKING_MODE = "sometimes";

    expect(() =>
      createLlmFromConfig(config(), {
        provider: "api",
        model: "remote-model",
        baseUrl: "https://gateway.example/v1",
      }),
    ).toThrow("MOSAIC_LLM_THINKING_MODE must be 'enabled' or 'disabled'");
  });

  it("disables Qwen thinking output for vLLM requests", () => {
    const handle = createLlmFromConfig(config());
    const params = (
      handle.llm as unknown as { invocationParams: () => Record<string, unknown> }
    ).invocationParams();

    expect(params.chat_template_kwargs).toEqual({ enable_thinking: false });
  });

  it("can defer sampling parameters to the sndr server preset", () => {
    const handle = createLlmFromConfig(config(), { useProviderSamplingDefaults: true });
    const params = (
      handle.llm as unknown as { invocationParams: () => Record<string, unknown> }
    ).invocationParams();

    expect(params.temperature).toBeUndefined();
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
