/**
 * Build a LangChain chat model from the bridge's active config.
 *
 * The runtime supports two paths:
 *   * **Anthropic** native via `ChatAnthropic` — MOSAIC's default per Plan §1
 *     (Claude Sonnet for parity with the ATLAS reference architecture).
 *   * **OpenAI-compatible** providers via `ChatOpenAI`: openai / xai /
 *     openrouter / ollama / vllm / lemonade / minimax / deepseek / api. This
 *     covers DeepSeek (≈1/10 cost, Plan §1) and the local Lemonade Qwen
 *     endpoint (zero-cost dev runs, Plan §13.3).
 *
 * Google native (`ChatGoogleGenerativeAI`) is deferred until a Layer-1 / 2
 * agent actually requests it; the dependency isn't pulled in until then.
 */

import { ChatAnthropic } from "@langchain/anthropic";
import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import { ChatOpenAI } from "@langchain/openai";
import type { MosaicConfig } from "../bridge/types.js";

/** Providers wired through the OpenAI-compatible Chat Completions API. */
const OPENAI_COMPATIBLE = new Set([
  "api",
  "openai",
  "xai",
  "openrouter",
  "ollama",
  "vllm",
  "lemonade",
  "minimax",
  "deepseek",
]);

const NATIVE_PROVIDERS = new Set(["anthropic"]);
const MOSAIC_USER_AGENT = "mosaic-ts/0.1.0";

/** Default base URLs per provider when the bridge config doesn't specify one.
 *
 * The Lemonade default below targets the standard `lemonade-server-dev`
 * binary on AMD Ryzen AI / NPU builds (8020/api/v0). If `--provider lemonade`
 * connects to a different port, override at one of these tiers (highest
 * precedence first):
 *   - CLI: pass `--baseUrl http://<host>:<port>/api/v0` (LlmOptions.baseUrl).
 *   - Env: export `LEMONADE_BASE_URL=...` (also `OLLAMA_BASE_URL`,
 *     `VLLM_BASE_URL`).
 *   - Config: set `backend_url` in the bridge config (config.set / .env).
 * Verify the actual URL from the `lemonade-server-dev` startup log.
 */
const DEFAULT_BASE_URL: Record<string, string | undefined> = {
  api: undefined,
  openai: undefined, // SDK default
  xai: "https://api.x.ai/v1",
  openrouter: "https://openrouter.ai/api/v1",
  ollama: "http://localhost:11434/v1",
  vllm: "http://localhost:8000/v1",
  lemonade: "http://localhost:8020/api/v0",
  minimax: "https://api.minimax.chat/v1",
  deepseek: "https://api.deepseek.com/v1",
};

/** Env var precedence: provider-specific first, then the generic `OPENAI_API_KEY`. */
const API_KEY_ENV: Record<string, string[]> = {
  api: ["MOSAIC_LLM_API_KEY"],
  openai: ["OPENAI_API_KEY"],
  xai: ["XAI_API_KEY", "OPENAI_API_KEY"],
  openrouter: ["OPENROUTER_API_KEY", "OPENAI_API_KEY"],
  ollama: [], // local, no key
  vllm: ["MOSAIC_VLLM_API_KEY", "OPENAI_API_KEY"], // optional for local, needed by hosted vLLM
  // Local lemonade-server-dev binaries don't use auth (same as ollama / vllm).
  // Hosted Lemonade with auth is not currently supported by this factory; if
  // needed, point a custom base URL through a proxy that injects the key.
  lemonade: [],
  minimax: ["MINIMAX_API_KEY", "OPENAI_API_KEY"],
  deepseek: ["DEEPSEEK_API_KEY", "OPENAI_API_KEY"],
  anthropic: ["ANTHROPIC_API_KEY"],
};

export interface LlmOptions {
  /** "deep" (default) → uses ``deep_think_llm``; "quick" → ``quick_think_llm``. */
  tier?: "deep" | "quick";
  /** Override the model from config. */
  model?: string;
  /** Override the temperature from config (default 0.2). */
  temperature?: number;
  /** Omit sampling fields so an OpenAI-compatible server preset owns them. */
  useProviderSamplingDefaults?: boolean;
  /** Override the provider from config (e.g. "lemonade" for local Qwen). */
  provider?: string;
  /** Override the base URL from config. */
  baseUrl?: string;
  /** Override the per-request max_tokens budget. */
  maxTokens?: number;
}

export interface LlmHandle {
  llm: BaseChatModel;
  provider: string;
  model: string;
  baseUrl: string | undefined;
}

function pickModel(config: MosaicConfig, tier: "deep" | "quick"): string {
  const key = tier === "deep" ? "deep_think_llm" : "quick_think_llm";
  const value = config[key];
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(
      `Bridge config is missing '${key}'. Run the bridge with a complete config or pass --model.`,
    );
  }
  return value;
}

function pickApiKey(provider: string): string | undefined {
  const candidates = API_KEY_ENV[provider] ?? [];
  for (const name of candidates) {
    const value = process.env[name];
    if (value && value.trim() !== "") {
      return value;
    }
  }
  return undefined;
}

function createAnthropic(
  config: MosaicConfig,
  options: LlmOptions,
  model: string,
): { llm: BaseChatModel; baseUrl: string | undefined } {
  const apiKey = pickApiKey("anthropic");
  if (!apiKey) {
    throw new Error(
      "Missing API key for provider 'anthropic'. Set ANTHROPIC_API_KEY in the environment.",
    );
  }
  const baseUrl = options.baseUrl ?? config.anthropic_base_url ?? undefined;

  // Plan §1: anthropic_effort drives the per-request thinking effort.
  // Anthropic's "extended thinking" surface keeps shifting; we forward the
  // string verbatim and let the SDK validate.
  const effortRaw = config.anthropic_effort;
  const effort = typeof effortRaw === "string" && effortRaw.trim() !== "" ? effortRaw : undefined;

  const llm = new ChatAnthropic({
    model,
    temperature: options.temperature ?? 0.2,
    ...(options.maxTokens ? { maxTokens: options.maxTokens } : {}),
    apiKey,
    ...(baseUrl ? { anthropicApiUrl: baseUrl } : {}),
    ...(effort ? { thinking: { type: "enabled", budget_tokens: effortToBudget(effort) } } : {}),
  });

  return { llm, baseUrl };
}

/** Map MOSAIC's 'low' / 'medium' / 'high' effort knob onto a thinking budget. */
function effortToBudget(effort: string): number {
  switch (effort.toLowerCase()) {
    case "low":
      return 1024;
    case "medium":
      return 4096;
    case "high":
      return 16_384;
    default:
      return 4096;
  }
}

function createOpenAiCompatible(
  config: MosaicConfig,
  options: LlmOptions,
  provider: string,
  model: string,
): { llm: BaseChatModel; baseUrl: string | undefined } {
  // Resolution order for base URL:
  //   1. options.baseUrl (CLI / direct override)
  //   2. provider-specific env (e.g. LEMONADE_BASE_URL)
  //   3. config.backend_url from the bridge config
  //   4. DEFAULT_BASE_URL[provider]
  const envBaseUrl = pickProviderEnvBaseUrl(provider);
  const resolvedBaseUrl =
    options.baseUrl ?? envBaseUrl ?? config.backend_url ?? DEFAULT_BASE_URL[provider];
  if (provider === "api" && !resolvedBaseUrl) {
    throw new Error("Missing base URL for provider 'api'. Set MOSAIC_LLM_BASE_URL.");
  }
  const baseUrl =
    provider === "api" && resolvedBaseUrl
      ? normalizeOpenAiCompatibleBaseUrl(resolvedBaseUrl)
      : resolvedBaseUrl;

  const apiKey = pickApiKey(provider);
  const requiresKey = (API_KEY_ENV[provider] ?? []).length > 0 && provider !== "vllm";
  if (requiresKey && !apiKey) {
    const names = API_KEY_ENV[provider]?.join(" or ");
    throw new Error(`Missing API key for provider '${provider}'. Set ${names} in the environment.`);
  }

  const llm = new ChatOpenAI({
    model,
    ...(!options.useProviderSamplingDefaults ? { temperature: options.temperature ?? 0.2 } : {}),
    ...(options.maxTokens ? { maxTokens: options.maxTokens } : {}),
    ...(provider === "vllm"
      ? { modelKwargs: { chat_template_kwargs: { enable_thinking: false } } }
      : {}),
    // Some OpenAI-compatible servers (Lemonade, Ollama, vLLM) reject empty
    // Authorization headers, so pass a placeholder when no key is configured.
    ...(apiKey ? { apiKey } : { apiKey: "not-needed" }),
    ...(baseUrl
      ? {
          configuration: {
            baseURL: baseUrl,
            ...(provider === "api" ? { fetch: mosaicApiFetch } : {}),
          },
        }
      : {}),
  });

  return { llm, baseUrl };
}

/** Per-provider base-URL env hooks. Empty string treated as unset. */
function pickProviderEnvBaseUrl(provider: string): string | undefined {
  for (const envName of BASE_URL_ENV[provider] ?? []) {
    const value = process.env[envName];
    if (value && value.trim() !== "") return value;
  }
  return undefined;
}

const BASE_URL_ENV: Record<string, string[]> = {
  api: ["MOSAIC_LLM_BASE_URL"],
  lemonade: ["LEMONADE_BASE_URL"],
  ollama: ["OLLAMA_BASE_URL"],
  vllm: ["VLLM_BASE_URL", "MOSAIC_RKE_VLLM_BASE_URL"],
};

function normalizeOpenAiCompatibleBaseUrl(value: string): string {
  let url: URL;
  try {
    url = new URL(value.trim());
  } catch {
    throw new Error("Invalid base URL for provider 'api'");
  }
  if (
    !new Set(["http:", "https:"]).has(url.protocol) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  ) {
    throw new Error("Invalid base URL for provider 'api'");
  }
  url.pathname = url.pathname
    .replace(/\/+$/, "")
    .replace(/\/chat\/completions$/, "")
    .replace(/\/+$/, "");
  return url.toString().replace(/\/$/, "");
}

function mosaicApiFetch(input: string | URL | Request, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  headers.set("User-Agent", MOSAIC_USER_AGENT);
  return fetch(input, { ...init, headers });
}

function envValue(name: string): string | undefined {
  const value = process.env[name];
  return value && value.trim() !== "" ? value.trim() : undefined;
}

function resolveMaxTokens(value: number | undefined): number | undefined {
  const raw = value ?? envValue("MOSAIC_LLM_MAX_TOKENS");
  if (raw === undefined) return undefined;
  const parsed = typeof raw === "number" ? raw : Number(raw);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error("MOSAIC_LLM_MAX_TOKENS must be a positive integer");
  }
  return parsed;
}

export function createLlmFromConfig(config: MosaicConfig, options: LlmOptions = {}): LlmHandle {
  const provider = (
    options.provider ??
    envValue("MOSAIC_LLM_PROVIDER") ??
    String(config.llm_provider ?? "anthropic")
  ).toLowerCase();
  const model =
    options.model ?? envValue("MOSAIC_LLM_MODEL") ?? pickModel(config, options.tier ?? "deep");
  const maxTokens = resolveMaxTokens(options.maxTokens);
  const resolvedOptions = maxTokens === undefined ? options : { ...options, maxTokens };

  if (NATIVE_PROVIDERS.has(provider)) {
    if (provider === "anthropic") {
      const { llm, baseUrl } = createAnthropic(config, resolvedOptions, model);
      return { llm, provider, model, baseUrl };
    }
    // Unreachable; kept for future native providers.
    throw new Error(`Provider '${provider}' marked native but has no factory.`);
  }

  if (OPENAI_COMPATIBLE.has(provider)) {
    const { llm, baseUrl } = createOpenAiCompatible(config, resolvedOptions, provider, model);
    return { llm, provider, model, baseUrl };
  }

  throw new Error(
    `Provider '${provider}' is not supported. Supported: ` +
      [...NATIVE_PROVIDERS, ...OPENAI_COMPATIBLE].sort().join(", ") +
      `. Google / Vertex native clients arrive when an agent first requests them.`,
  );
}
