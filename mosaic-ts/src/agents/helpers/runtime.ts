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

export function buildLlmCall(agentId: string, handle: LlmHandle): LlmCallRecord {
  return {
    ts: new Date().toISOString(),
    agent: agentId,
    model: handle.model,
    provider: handle.provider,
    // Token counts are 0 here. Phase 3 scorecard will plumb provider
    // callbacks for accurate counts.
    prompt_tokens: 0,
    completion_tokens: 0,
    cost_usd: 0,
  };
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

  switch (agent) {
    case "central_bank":
      pushString(parts, "stance", obj, "stance");
      pushNumber(parts, "bps", obj, "key_rate_change_bps");
      break;
    case "geopolitical":
      pushNumber(parts, "level", obj, "escalation_level");
      pushArrayLength(parts, "zones", obj, "hot_zones");
      break;
    case "china":
      pushString(parts, "policy", obj, "policy_direction");
      pushArrayLength(parts, "focus", obj, "sector_focus");
      break;
    case "dollar":
      pushString(parts, "dxy", obj, "dxy_trend");
      pushString(parts, "cny", obj, "cny_pressure");
      break;
    case "yield_curve":
      pushString(parts, "curve", obj, "curve_shape");
      pushString(parts, "recession", obj, "recession_signal");
      break;
    case "commodities":
      pushString(parts, "oil", obj, "oil_regime");
      pushString(parts, "metals", obj, "metals_regime");
      break;
    case "volatility":
      pushString(parts, "vix", obj, "vix_regime");
      pushString(parts, "filter", obj, "regime_filter");
      break;
    case "emerging_markets":
      pushString(parts, "em", obj, "em_relative");
      pushString(parts, "flow", obj, "capital_flow");
      break;
    case "news_sentiment":
      pushNumber(parts, "retail", obj, "retail_sentiment_score", 2);
      pushArrayLength(parts, "topics", obj, "hot_topics");
      break;
    case "institutional_flow":
      pushNumber(parts, "main_flow", obj, "main_net_flow_cny", 0);
      pushArrayLength(parts, "sectors", obj, "sectors_in_out");
      break;
    case "relationship_mapper":
      pushArrayLength(parts, "chains", obj, "supply_chains");
      pushArrayLength(parts, "risks", obj, "contagion_risks");
      break;
    case "druckenmiller":
    case "aschenbrenner":
    case "baker":
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
