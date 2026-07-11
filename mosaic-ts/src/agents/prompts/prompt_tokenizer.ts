import { getEncoding } from "js-tiktoken";

export const PROMPT_TOKENIZER_ID = "cl100k_base" as const;
export const PROMPT_TOKENIZER_PACKAGE = "js-tiktoken" as const;
export const PROMPT_TOKENIZER_VERSION = "1.0.21" as const;
export const PROMPT_VISIBLE_CONTRACT_CAP_TOKENS = 8_192;
export const PROMPT_ABSOLUTE_SYSTEM_CAP_TOKENS = 32_768;
export const PROMPT_MIN_RESERVED_CONTEXT_RATIO = 0.5;
export const PROMPT_DEFAULT_CONTEXT_WINDOW_TOKENS = 131_072;

let tokenizer: ReturnType<typeof getEncoding> | null = null;

export interface RuntimeSystemPromptTokenMeasurement {
  tokenizer_id: typeof PROMPT_TOKENIZER_ID;
  tokenizer_version: typeof PROMPT_TOKENIZER_VERSION;
  context_window_tokens: number;
  system_prompt_tokens: number;
  system_prompt_cap_tokens: number;
  token_budget_breached: boolean;
}

export function countPromptTokens(value: string): number {
  tokenizer ??= getEncoding(PROMPT_TOKENIZER_ID);
  return tokenizer.encode(value).length;
}

export function measureRuntimeSystemPromptTokens(
  systemPrompt: string,
  contextWindowTokens = runtimeContextWindowTokens(),
): RuntimeSystemPromptTokenMeasurement {
  if (!Number.isInteger(contextWindowTokens) || contextWindowTokens <= 0) {
    throw new Error("prompt_token_budget_context_window_invalid");
  }
  const systemPromptTokens = countPromptTokens(systemPrompt);
  const systemPromptCapTokens = Math.min(
    PROMPT_ABSOLUTE_SYSTEM_CAP_TOKENS,
    Math.floor(contextWindowTokens * 0.25),
  );
  return {
    tokenizer_id: PROMPT_TOKENIZER_ID,
    tokenizer_version: PROMPT_TOKENIZER_VERSION,
    context_window_tokens: contextWindowTokens,
    system_prompt_tokens: systemPromptTokens,
    system_prompt_cap_tokens: systemPromptCapTokens,
    token_budget_breached:
      systemPromptTokens > systemPromptCapTokens ||
      contextWindowTokens - systemPromptTokens <
        contextWindowTokens * PROMPT_MIN_RESERVED_CONTEXT_RATIO,
  };
}

function runtimeContextWindowTokens(): number {
  const raw = process.env.MOSAIC_LLM_CONTEXT_WINDOW_TOKENS?.trim();
  if (!raw) return PROMPT_DEFAULT_CONTEXT_WINDOW_TOKENS;
  return Number.parseInt(raw, 10);
}
