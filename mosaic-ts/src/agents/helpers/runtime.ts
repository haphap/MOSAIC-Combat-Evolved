import type { LlmHandle } from "../../llm/factory.js";
import { redactSensitiveText } from "../../security/redaction.js";
import type { LlmCallRecord } from "../types.js";

export const DEFAULT_AGENT_TIMEOUT_SECONDS = 300;

export type AgentLayer = "L1" | "L2" | "L3" | "L4";

export class AgentTimeoutError extends Error {
  readonly label: string;
  readonly timeoutMs: number;

  constructor(label: string, timeoutMs: number) {
    super(`${label} timed out after ${formatDurationMs(timeoutMs)}`);
    this.name = "AgentTimeoutError";
    this.label = label;
    this.timeoutMs = timeoutMs;
  }
}

export function parseAgentTimeoutSeconds(value: string | undefined): number | undefined {
  if (value === undefined) return undefined;
  const raw = value.trim().toLowerCase();
  if (!raw) return undefined;
  if (raw === "off" || raw === "none" || raw === "false") return 0;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) {
    throw new Error(`invalid agent timeout seconds: ${value}`);
  }
  return parsed;
}

export function resolveAgentTimeoutMs(
  explicitSeconds?: number,
  envValue = process.env.MOSAIC_AGENT_TIMEOUT_SECONDS,
): number {
  const seconds =
    explicitSeconds ?? parseAgentTimeoutSeconds(envValue) ?? DEFAULT_AGENT_TIMEOUT_SECONDS;
  if (!Number.isFinite(seconds)) {
    throw new Error(`invalid agent timeout seconds: ${seconds}`);
  }
  if (seconds <= 0) return 0;
  return Math.ceil(seconds * 1000);
}

export async function withAgentTimeout<T>(
  operation: (signal: AbortSignal) => Promise<T>,
  timeoutMs: number,
  label: string,
): Promise<T> {
  if (timeoutMs <= 0) {
    return operation(new AbortController().signal);
  }

  const controller = new AbortController();
  let timeout: NodeJS.Timeout | undefined;
  const running = operation(controller.signal);
  try {
    return await Promise.race([
      running,
      new Promise<T>((_resolve, reject) => {
        timeout = setTimeout(() => {
          const err = new AgentTimeoutError(label, timeoutMs);
          controller.abort(err);
          reject(err);
        }, timeoutMs);
      }),
    ]);
  } finally {
    if (timeout) clearTimeout(timeout);
    running.catch(() => undefined);
  }
}

export function formatAgentEvent(
  event: "start" | "phase" | "done" | "timeout" | "error",
  layer: AgentLayer,
  agentId: string,
  fields: ReadonlyArray<string> = [],
): string {
  const extra = fields.filter((f) => f.trim()).join(" ");
  return `[agent:${event}] ${layer} ${agentId}${extra ? ` ${extra}` : ""}`;
}

export function formatDurationMs(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "0ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const totalSeconds = Math.round(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m${String(seconds).padStart(2, "0")}s`;
}

export function buildLlmCall(
  agentId: string,
  handle: LlmHandle,
  usage: LlmTokenUsage = { promptTokens: 0, completionTokens: 0 },
): LlmCallRecord {
  return {
    ts: new Date().toISOString(),
    agent: agentId,
    model: handle.model,
    provider: handle.provider,
    prompt_tokens: usage.promptTokens,
    completion_tokens: usage.completionTokens,
    cost_usd: 0,
  };
}

export interface LlmTokenUsage {
  promptTokens: number;
  completionTokens: number;
}

export function extractLlmTokenUsage(message: unknown): LlmTokenUsage {
  const record = asRecord(message);
  const responseMetadata = asRecord(record?.response_metadata);
  const usage = asRecord(record?.usage_metadata) ?? asRecord(responseMetadata?.usage);
  const tokenUsage = asRecord(responseMetadata?.tokenUsage);
  return {
    promptTokens:
      numberField(usage ?? {}, "input_tokens") ??
      numberField(tokenUsage ?? {}, "promptTokens") ??
      numberField(tokenUsage ?? {}, "prompt_tokens") ??
      0,
    completionTokens:
      numberField(usage ?? {}, "output_tokens") ??
      numberField(tokenUsage ?? {}, "completionTokens") ??
      numberField(tokenUsage ?? {}, "completion_tokens") ??
      0,
  };
}

export function formatTokenMetricFields(
  promptTokens: number,
  completionTokens: number,
  llmElapsedMs: number,
): string[] {
  const fields = [
    `prompt_tokens=${Math.max(0, Math.round(promptTokens))}`,
    `completion_tokens=${Math.max(0, Math.round(completionTokens))}`,
    `llm_elapsed_ms=${Math.max(0, Math.round(llmElapsedMs))}`,
  ];
  if (completionTokens > 0 && llmElapsedMs > 0) {
    fields.push(`completion_tps=${(completionTokens / (llmElapsedMs / 1000)).toFixed(2)}`);
  }
  return fields;
}

export function safeErrorMessage(err: unknown, maxLength = 220): string {
  const raw = err instanceof Error ? err.message : String(err);
  const singleLine = redactSensitiveText(raw).replace(/\s+/g, " ").trim();
  if (singleLine.length <= maxLength) return singleLine;
  return `${singleLine.slice(0, maxLength - 3)}...`;
}

export function summarizeAgentOutput(output: unknown): string {
  const obj = asRecord(output);
  if (!obj) return "output=unknown";

  const agent = stringField(obj, "agent");
  const parts: string[] = [];

  if (
    agent &&
    [
      "china",
      "us_economy",
      "central_bank",
      "dollar",
      "yield_curve",
      "commodities",
      "geopolitical",
      "volatility",
      "market_breadth",
      "institutional_flow",
    ].includes(agent)
  ) {
    pushString(parts, "direction", obj, "direction");
    pushNumber(parts, "strength", obj, "strength", 0);
    pushString(parts, "horizon", obj, "horizon");
    pushNumber(parts, "conf", obj, "confidence", 2);
    pushArrayLength(parts, "drivers", obj, "key_drivers");
    return parts.join(" ");
  }

  switch (agent) {
    case "relationship_mapper":
      pushArrayLength(parts, "chains", obj, "supply_chains");
      pushArrayLength(parts, "risks", obj, "contagion_risks");
      break;
    case "druckenmiller":
    case "munger":
    case "burry":
    case "ackman":
      pushArrayLength(parts, "picks", obj, "picks");
      break;
    case "cro":
      pushArrayLength(parts, "rejected", obj, "rejected_picks");
      pushArrayLength(parts, "black_swan", obj, "black_swan_scenarios");
      break;
    case "alpha_discovery":
      pushArrayLength(parts, "novel", obj, "novel_picks");
      break;
    case "autonomous_execution":
      pushArrayLength(parts, "trades", obj, "trades");
      break;
    case "cio":
      pushArrayLength(parts, "actions", obj, "portfolio_actions");
      break;
    default:
      if (Array.isArray(obj.longs) || Array.isArray(obj.shorts)) {
        pushNumber(parts, "score", obj, "sector_score", 2);
        pushArrayLength(parts, "longs", obj, "longs");
        pushArrayLength(parts, "shorts", obj, "shorts");
      } else {
        parts.push("output=ok");
      }
      break;
  }

  pushNumber(parts, "conf", obj, "confidence", 2);
  pushArrayLength(parts, "drivers", obj, "key_drivers");
  return parts.join(" ") || "output=ok";
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function stringField(obj: Record<string, unknown>, key: string): string | undefined {
  const value = obj[key];
  return typeof value === "string" ? value : undefined;
}

function numberField(obj: Record<string, unknown>, key: string): number | undefined {
  const value = obj[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function pushString(
  parts: string[],
  label: string,
  obj: Record<string, unknown>,
  key: string,
): void {
  const value = stringField(obj, key);
  if (value) parts.push(`${label}=${value}`);
}

function pushNumber(
  parts: string[],
  label: string,
  obj: Record<string, unknown>,
  key: string,
  digits = 0,
): void {
  const value = numberField(obj, key);
  if (value !== undefined) parts.push(`${label}=${value.toFixed(digits)}`);
}

function pushArrayLength(
  parts: string[],
  label: string,
  obj: Record<string, unknown>,
  key: string,
): void {
  const value = obj[key];
  if (Array.isArray(value)) parts.push(`${label}=${value.length}`);
}
