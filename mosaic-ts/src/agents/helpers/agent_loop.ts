/**
 * Inline tool-call loop for Layer-1+ agent nodes (Plan §11.2 2B-3).
 *
 * Why a separate helper: ``runToolReportChain`` from 2A.2 assumes the loop
 * lives at the LangGraph level (analyst → ToolNode → analyst). 2B does not
 * yet have the graph wired, so each agent node runs its own bounded loop
 * here. 2E may convert this to a real LangGraph subgraph; the surface here
 * stays stable.
 *
 * Loop semantics:
 *   1. bind tools, invoke LLM with [system, ...messages]
 *   2. if no tool_calls → return content as the analysis text
 *   3. for each tool_call → invoke local tool, append ToolMessage
 *   4. repeat until step-2 hits or maxLoops reached
 *
 * Returns the final analysis string + a record of how many invocations and
 * tool calls happened (for the LlmCallRecord ledger in DailyCycleState).
 */

import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import {
  AIMessage,
  type BaseMessage,
  HumanMessage,
  SystemMessage,
  ToolMessage,
} from "@langchain/core/messages";
import type { StructuredToolInterface } from "@langchain/core/tools";
import { canonicalJsonHash } from "./canonical_json.js";
import { extractTextContent } from "./content.js";
import type {
  PrivateKnotFrozenInitialToolResult,
  PrivateKnotModelContextResult,
  ToolStatus,
} from "./private_knot_boundary.js";
import { isProcessOnlyReportText, stripProcessOnlyReportPrefix } from "./process_narration.js";
import { extractLlmTokenUsage } from "./runtime.js";

export interface AgentToolLoopOptions {
  llm: BaseChatModel;
  tools: ReadonlyArray<StructuredToolInterface>;
  /** System prompt body (zh / en / Bilingual) for this agent. */
  systemMessage: string;
  /** Human messages prepared by the caller (e.g. `as_of_date` context). */
  initialMessages: ReadonlyArray<BaseMessage>;
  /** Cap loop iterations to bound LLM cost; default 6. */
  maxLoops?: number;
  /** Full latest-tool replay budget in chars; 0 means unlimited. */
  replayFullToolMaxChars?: number;
  /** Deterministic role-required evidence to collect before the first LLM turn. */
  initialToolCalls?: ReadonlyArray<AgentInitialToolCall>;
  /**
   * Whether tools remain advertised to the model after deterministic initial
   * collection. Default true. Set false when the runtime owns the only allowed
   * call and the model must analyze that frozen result without changing scope.
   */
  allowModelToolCalls?: boolean;
  /** Forward LLM stderr / debug logs through this channel (default: silent). */
  onLog?: (msg: string) => void;
  /** Abort signal for the current agent wall-clock timeout. */
  signal?: AbortSignal;
  /** Runtime-owned identity for the current agent/stage invocation. */
  agentInvocationId?: string;
  prepareModelContext?: (
    initialToolResults: ReadonlyArray<PrivateKnotFrozenInitialToolResult>,
  ) => Promise<PrivateKnotModelContextResult>;
}

export interface AgentInitialToolCall {
  name: string;
  args: Record<string, unknown>;
}

export interface AgentToolLoopResult {
  /**
   * Final assistant text after process-narration prefixes stripped. Empty
   * string if the loop exhausted maxLoops without producing a non-tool-call
   * reply.
   */
  analysisText: string;
  /** How many times the LLM was invoked in this loop. */
  llmInvocations: number;
  /** Total tool_calls dispatched across all iterations. */
  toolCalls: number;
  /** Tool calls served from the per-agent fingerprint cache. */
  toolCacheHits: number;
  /** Registered tool invocations that reached the bridge/local tool. */
  toolExecutions: number;
  /** Observed provider prompt tokens for analysis-loop calls. */
  promptTokens: number;
  /** Observed provider completion tokens for analysis-loop calls. */
  completionTokens: number;
  /** Wall time spent awaiting analysis-loop LLM calls. */
  llmElapsedMs: number;
  /** The full message thread including ToolMessages, useful for debugging. */
  messages: BaseMessage[];
  /** Per-tool call status ledger consumed by private policy enforcement. */
  toolStatuses: ToolStatus[];
  modelContext: PrivateKnotModelContextResult | null;
  effectiveModelInputHash: string;
}

const DEFAULT_MAX_LOOPS = 6;
const DEFAULT_TOOL_OUTPUT_MAX_CHARS = 0;
const DEFAULT_REPLAY_FULL_TOOL_MAX_CHARS = 0;
const PRIOR_TOOL_REPLAY_CHARS = 800;

export interface ToolReplayEntry {
  fingerprint: string;
  output: string;
}

export interface CompactedToolOutput {
  text: string;
  truncated: boolean;
  originalChars: number;
}

export function parseToolOutputMaxChars(value: string | undefined): number | undefined {
  if (value === undefined) return undefined;
  const raw = value.trim().toLowerCase();
  if (!raw) return undefined;
  if (raw === "off" || raw === "none" || raw === "false") return 0;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed < 0) {
    throw new Error(`invalid tool output max chars: ${value}`);
  }
  return parsed;
}

export function resolveToolOutputMaxChars(
  explicit?: number,
  envValue = process.env.MOSAIC_AGENT_TOOL_OUTPUT_MAX_CHARS,
): number {
  const chars = explicit ?? parseToolOutputMaxChars(envValue) ?? DEFAULT_TOOL_OUTPUT_MAX_CHARS;
  if (!Number.isFinite(chars)) {
    throw new Error(`invalid tool output max chars: ${chars}`);
  }
  return Math.max(0, Math.floor(chars));
}

export function resolveReplayFullToolMaxChars(
  envValue = process.env.MOSAIC_AGENT_REPLAY_FULL_TOOL_MAX_CHARS,
): number {
  const chars = parseToolOutputMaxChars(envValue) ?? DEFAULT_REPLAY_FULL_TOOL_MAX_CHARS;
  if (!Number.isFinite(chars)) {
    throw new Error(`invalid replay full tool max chars: ${chars}`);
  }
  return Math.max(0, Math.floor(chars));
}

export function compactToolOutput(output: string, maxChars: number): CompactedToolOutput {
  const originalChars = output.length;
  if (maxChars <= 0 || originalChars <= maxChars) {
    return { text: output, truncated: false, originalChars };
  }
  const marker = `\n\n[tool_output_truncated original_chars=${originalChars}]`;
  if (maxChars <= marker.length) {
    return { text: output.slice(0, maxChars), truncated: true, originalChars };
  }
  return {
    text: `${output.slice(0, maxChars - marker.length)}${marker}`,
    truncated: true,
    originalChars,
  };
}

function toolOutputStatusMetadata(output: string): Pick<ToolStatus, "fallback" | "as_of"> {
  const parsed = parseToolOutputJson(output);
  if (!parsed) return { fallback: false };
  const fallback = [
    parsed.fallback,
    parsed.is_fallback,
    parsed.source,
    parsed.data_source,
    parsed.status,
    parsed.tool_status,
  ].some(isFallbackMarker);
  const asOf = firstString(parsed.as_of, parsed.as_of_date, parsed.date, parsed.timestamp);
  return {
    fallback,
    ...(asOf ? { as_of: asOf } : {}),
  };
}

function parseToolOutputJson(output: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(output);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    return parsed as Record<string, unknown>;
  } catch {
    return null;
  }
}

function isFallbackMarker(value: unknown): boolean {
  if (value === true) return true;
  return (
    typeof value === "string" &&
    ["fallback", "true", "degraded_fallback", "primary_fallback"].includes(value.toLowerCase())
  );
}

function firstString(...values: unknown[]): string | undefined {
  return values.find((value): value is string => typeof value === "string" && value.length > 0);
}

function hasToolCalls(message: BaseMessage): message is AIMessage {
  return message.getType() === "ai" && ((message as AIMessage).tool_calls ?? []).length > 0;
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, entry]) => [key, canonicalize(entry)]),
    );
  }
  return value === undefined ? null : value;
}

function sha256Canonical(value: unknown): string {
  return canonicalJsonHash(canonicalize(value));
}

export function toolArgsFingerprint(args: unknown): string {
  return sha256Canonical({ schema_version: "tool_args_fingerprint_v1", args: args ?? {} });
}

export function toolResultFingerprint(output: string): string {
  let result: unknown = output;
  try {
    result = JSON.parse(output);
  } catch {
    // Non-JSON tool output is hashed as its exact text.
  }
  return sha256Canonical({ schema_version: "tool_result_fingerprint_v1", result });
}

export function toolSourceFingerprint(input: {
  name: string;
  argsFingerprint: string;
  resultFingerprint: string;
  status: "current" | "fallback" | "missing" | "tool_failed";
  asOf?: string;
}): string {
  return sha256Canonical({
    schema_version: "tool_source_fingerprint_v1",
    adapter_id: "agent_tool_loop_status",
    adapter_version: "1",
    tool: input.name,
    args_fingerprint: input.argsFingerprint,
    result_fingerprint: input.resultFingerprint,
    status: input.status,
    as_of: input.asOf ?? null,
  });
}

export function toolCallFingerprint(name: string | undefined, args: unknown): string {
  const toolName = name || "unknown";
  const hash = canonicalJsonHash(canonicalize(args ?? {})).slice("sha256:".length, 17);
  return `${toolName}#${hash}`;
}

interface CachedToolResult {
  output: string;
  failed: boolean;
  fallback: boolean;
  asOf?: string;
  argsFingerprint: string;
  resultFingerprint: string;
  sourceFingerprint: string;
}

function buildToolStatus(input: {
  name: string;
  callId: string;
  agentInvocationId?: string;
  args: unknown;
  shortFingerprint: string;
  cached: CachedToolResult;
  cacheHit: boolean;
  missing?: boolean;
}): ToolStatus {
  return {
    name: input.name,
    call_id: input.callId,
    ...(input.agentInvocationId ? { agent_invocation_id: input.agentInvocationId } : {}),
    called: true,
    failed: input.cached.failed,
    missing: input.missing ?? false,
    fallback: input.cached.fallback,
    cache_hit: input.cacheHit,
    args: input.args,
    fingerprint: input.shortFingerprint,
    args_fingerprint: input.cached.argsFingerprint,
    result_fingerprint: input.cached.resultFingerprint,
    source_fingerprint: input.cached.sourceFingerprint,
    ...(input.cached.asOf ? { as_of: input.cached.asOf } : {}),
  };
}

function cachedToolResult(input: {
  name: string;
  args: unknown;
  output: string;
  failed: boolean;
  fallback?: boolean;
  asOf?: string;
}): CachedToolResult {
  const argsFingerprint = toolArgsFingerprint(input.args);
  const resultFingerprint = toolResultFingerprint(input.output);
  const status = input.failed ? "tool_failed" : input.fallback ? "fallback" : "current";
  return {
    output: input.output,
    failed: input.failed,
    fallback: input.fallback ?? false,
    ...(input.asOf ? { asOf: input.asOf } : {}),
    argsFingerprint,
    resultFingerprint,
    sourceFingerprint: toolSourceFingerprint({
      name: input.name,
      argsFingerprint,
      resultFingerprint,
      status,
      ...(input.asOf ? { asOf: input.asOf } : {}),
    }),
  };
}

function missingToolResult(name: string, args: unknown): CachedToolResult {
  const output = `Tool '${name}' is not registered for this agent.`;
  const argsFingerprint = toolArgsFingerprint(args);
  const resultFingerprint = toolResultFingerprint(output);
  return {
    output,
    failed: false,
    fallback: false,
    argsFingerprint,
    resultFingerprint,
    sourceFingerprint: toolSourceFingerprint({
      name,
      argsFingerprint,
      resultFingerprint,
      status: "missing",
    }),
  };
}

function compactPriorToolReplayText(output: string): string {
  if (output.length <= PRIOR_TOOL_REPLAY_CHARS) return output;
  const headChars = Math.floor(PRIOR_TOOL_REPLAY_CHARS * 0.7);
  const tailChars = PRIOR_TOOL_REPLAY_CHARS - headChars;
  return (
    `${output.slice(0, headChars)}\n` +
    `[prior_tool_output_compacted original_chars=${output.length}]\n` +
    output.slice(-tailChars)
  );
}

function renderToolReplaySummary(
  entries: ReadonlyArray<ToolReplayEntry>,
  latestByFingerprint: ReadonlyMap<string, ToolReplayEntry>,
  fullEntries: ReadonlySet<ToolReplayEntry>,
): HumanMessage | undefined {
  if (entries.length === 0) return undefined;
  const lines = entries.map((entry) => {
    const latest = latestByFingerprint.get(entry.fingerprint) === entry;
    const full = latest && fullEntries.has(entry);
    const label = full ? "full" : latest ? "full_budget_memo" : "older_duplicate_memo";
    const text = full ? entry.output : compactPriorToolReplayText(entry.output);
    return `- ${entry.fingerprint} [${label}]:\n  ${text.replaceAll("\n", "\n  ")}`;
  });
  return new HumanMessage(`Prior tool results retained:\n${lines.join("\n")}`);
}

function isToolReplaySummary(message: BaseMessage): boolean {
  return (
    message.getType() === "human" &&
    extractTextContent(message.content as unknown).startsWith("Prior tool results retained:\n")
  );
}

function collectToolReplayEntries(messages: ReadonlyArray<BaseMessage>): ToolReplayEntry[] {
  const entries: ToolReplayEntry[] = [];
  let droppingToolReplies = false;
  let pendingToolCalls = new Map<string, string>();
  for (const message of messages) {
    if (droppingToolReplies && message.getType() !== "tool") {
      droppingToolReplies = false;
      pendingToolCalls = new Map();
    }
    if (hasToolCalls(message)) {
      pendingToolCalls = new Map(
        (message.tool_calls ?? []).map((call) => [
          call.id ?? "",
          toolCallFingerprint(call.name, call.args ?? {}),
        ]),
      );
      droppingToolReplies = true;
      continue;
    }
    if (droppingToolReplies && message.getType() === "tool") {
      const toolMessage = message as ToolMessage;
      entries.push({
        fingerprint: pendingToolCalls.get(toolMessage.tool_call_id) ?? "unknown#unknown",
        output: extractTextContent(toolMessage.content as unknown),
      });
    }
  }
  return entries;
}

function latestToolReplayEntries(
  entries: ReadonlyArray<ToolReplayEntry>,
): Map<string, ToolReplayEntry> {
  const latestByFingerprint = new Map<string, ToolReplayEntry>();
  for (const entry of entries) latestByFingerprint.set(entry.fingerprint, entry);
  return latestByFingerprint;
}

function replayFullEntries(
  entries: ReadonlyArray<ToolReplayEntry>,
  latestByFingerprint: ReadonlyMap<string, ToolReplayEntry>,
  maxFullChars: number,
): Set<ToolReplayEntry> {
  const fullCandidates = entries.filter(
    (entry) => latestByFingerprint.get(entry.fingerprint) === entry,
  );
  if (maxFullChars <= 0) return new Set(fullCandidates);
  const fullEntries = new Set<ToolReplayEntry>();
  let remaining = maxFullChars;
  for (let index = fullCandidates.length - 1; index >= 0; index--) {
    const entry = fullCandidates[index];
    if (!entry) continue;
    if (entry.output.length > remaining) continue;
    fullEntries.add(entry);
    remaining -= entry.output.length;
  }
  return fullEntries;
}

function flushToolReplaySegment(
  pruned: BaseMessage[],
  segmentEntries: ToolReplayEntry[],
  latestByFingerprint: ReadonlyMap<string, ToolReplayEntry>,
  fullEntries: ReadonlySet<ToolReplayEntry>,
): void {
  const summary = renderToolReplaySummary(segmentEntries, latestByFingerprint, fullEntries);
  if (summary) pruned.push(summary);
  segmentEntries.length = 0;
}

export function pruneConsumedToolHistoryWithEntries(
  messages: ReadonlyArray<BaseMessage>,
  priorEntries: ReadonlyArray<ToolReplayEntry>,
  maxFullChars = resolveReplayFullToolMaxChars(),
): { messages: BaseMessage[]; entries: ToolReplayEntry[] } {
  const newEntries = collectToolReplayEntries(messages);
  const entries = [...priorEntries, ...newEntries];
  const latestByFingerprint = latestToolReplayEntries(entries);
  const fullEntries = replayFullEntries(entries, latestByFingerprint, maxFullChars);
  const pruned: BaseMessage[] = [];
  let droppingToolReplies = false;
  const segmentEntries: ToolReplayEntry[] = [];
  let newEntryIndex = 0;
  let renderedPriorEntries = false;

  for (const message of messages) {
    if (droppingToolReplies && message.getType() !== "tool") {
      flushToolReplaySegment(pruned, segmentEntries, latestByFingerprint, fullEntries);
      droppingToolReplies = false;
    }
    if (isToolReplaySummary(message) && priorEntries.length > 0) {
      if (!renderedPriorEntries) {
        const summary = renderToolReplaySummary(priorEntries, latestByFingerprint, fullEntries);
        if (summary) pruned.push(summary);
        renderedPriorEntries = true;
      }
      continue;
    }
    if (hasToolCalls(message)) {
      const content = extractTextContent(message.content as unknown).trim();
      if (content) {
        pruned.push(new AIMessage(content));
      }
      droppingToolReplies = true;
      continue;
    }
    if (droppingToolReplies && message.getType() === "tool") {
      const entry = newEntries[newEntryIndex++];
      if (entry) segmentEntries.push(entry);
      continue;
    }
    pruned.push(message);
  }
  flushToolReplaySegment(pruned, segmentEntries, latestByFingerprint, fullEntries);
  if (priorEntries.length > 0 && !renderedPriorEntries) {
    const summary = renderToolReplaySummary(priorEntries, latestByFingerprint, fullEntries);
    if (summary) pruned.push(summary);
  }
  return { messages: pruned, entries };
}

export function pruneConsumedToolHistory(messages: ReadonlyArray<BaseMessage>): BaseMessage[] {
  return pruneConsumedToolHistoryWithEntries(messages, []).messages;
}

export async function runAgentToolLoop(opts: AgentToolLoopOptions): Promise<AgentToolLoopResult> {
  const maxLoops = opts.maxLoops ?? DEFAULT_MAX_LOOPS;
  const toolOutputMaxChars = resolveToolOutputMaxChars();
  const replayFullToolMaxChars = opts.replayFullToolMaxChars ?? resolveReplayFullToolMaxChars();
  const toolByName = new Map(opts.tools.map((t) => [t.name, t] as const));
  const messages: BaseMessage[] = [...opts.initialMessages];
  let replayMessages: BaseMessage[] = [...opts.initialMessages];
  let llmInvocations = 0;
  let toolCalls = 0;
  let toolCacheHits = 0;
  let toolExecutions = 0;
  let promptTokens = 0;
  let completionTokens = 0;
  let llmElapsedMs = 0;
  const toolStatuses: ToolStatus[] = [];
  const initialToolResults: PrivateKnotFrozenInitialToolResult[] = [];
  // ponytail: per-agent cache; make it shared only if duplicate tool IO remains costly.
  const toolOutputCache = new Map<string, CachedToolResult>();
  let toolReplayEntries: ToolReplayEntry[] = [];

  // Some BaseChatModel subclasses lack bindTools; the caller is responsible
  // for picking a provider that supports tool-calling. Fail loud rather than
  // silently dropping the tools.
  if (opts.allowModelToolCalls !== false && !opts.llm.bindTools) {
    throw new Error(
      "runAgentToolLoop: provider chat model does not implement bindTools — " +
        "switch to a provider/model that supports tool calling (anthropic, openai, ...).",
    );
  }
  const llmWithTools =
    opts.allowModelToolCalls === false
      ? opts.llm
      : opts.llm.bindTools?.(opts.tools as StructuredToolInterface[]);
  if (!llmWithTools) {
    throw new Error("runAgentToolLoop: provider failed to bind the registered tools.");
  }

  if (opts.initialToolCalls?.length) {
    const calls = opts.initialToolCalls.map((call, index) => ({
      id: `initial_tool_${index + 1}`,
      name: call.name,
      args: call.args,
      type: "tool_call" as const,
    }));
    const ai = new AIMessage({ content: "Collecting role-required evidence.", tool_calls: calls });
    messages.push(ai);
    replayMessages.push(ai);
    opts.onLog?.(
      `tools=${calls.length} names=${calls.map((call) => call.name).join(",")} fingerprints=${calls
        .map((call) => toolCallFingerprint(call.name, call.args))
        .join(",")}`,
    );
    for (const call of calls) {
      const name = call.name;
      const fingerprint = toolCallFingerprint(call.name, call.args);
      toolCalls++;
      const tool = toolByName.get(name);
      if (!tool) {
        opts.onLog?.(`unknown tool '${name}', stubbing reply`);
        const cached = missingToolResult(name, call.args);
        const status = buildToolStatus({
          name,
          callId: call.id,
          ...(opts.agentInvocationId ? { agentInvocationId: opts.agentInvocationId } : {}),
          args: call.args,
          shortFingerprint: fingerprint,
          cached,
          cacheHit: false,
          missing: true,
        });
        toolStatuses.push(status);
        if (opts.prepareModelContext) {
          initialToolResults.push(frozenInitialToolResult(call, status, cached.output));
        }
        const toolMessage = new ToolMessage({
          content: cached.output,
          tool_call_id: call.id,
        });
        messages.push(toolMessage);
        replayMessages.push(toolMessage);
        continue;
      }
      toolExecutions++;
      let output: string;
      try {
        const raw = await tool.invoke(call.args, opts.signal ? { signal: opts.signal } : undefined);
        output = typeof raw === "string" ? raw : String(raw);
        const metadata = toolOutputStatusMetadata(output);
        const cached = cachedToolResult({
          name,
          args: call.args,
          output,
          failed: false,
          fallback: metadata.fallback,
          ...(metadata.as_of ? { asOf: metadata.as_of } : {}),
        });
        toolOutputCache.set(fingerprint, cached);
        const status = buildToolStatus({
          name,
          callId: call.id,
          ...(opts.agentInvocationId ? { agentInvocationId: opts.agentInvocationId } : {}),
          args: call.args,
          shortFingerprint: fingerprint,
          cached,
          cacheHit: false,
        });
        toolStatuses.push(status);
        if (opts.prepareModelContext) {
          initialToolResults.push(frozenInitialToolResult(call, status, output));
        }
      } catch (err) {
        output = `Tool '${name}' raised: ${(err as Error).message}`;
        opts.onLog?.(output);
        const cached = cachedToolResult({ name, args: call.args, output, failed: true });
        toolOutputCache.set(fingerprint, cached);
        const status = buildToolStatus({
          name,
          callId: call.id,
          ...(opts.agentInvocationId ? { agentInvocationId: opts.agentInvocationId } : {}),
          args: call.args,
          shortFingerprint: fingerprint,
          cached,
          cacheHit: false,
        });
        toolStatuses.push(status);
        if (opts.prepareModelContext) {
          initialToolResults.push(frozenInitialToolResult(call, status, output));
        }
      }
      const compacted = compactToolOutput(output, toolOutputMaxChars);
      const toolMessage = new ToolMessage({ content: compacted.text, tool_call_id: call.id });
      messages.push(toolMessage);
      replayMessages.push(toolMessage);
    }
  }

  const modelContext = opts.prepareModelContext
    ? await opts.prepareModelContext(initialToolResults)
    : null;
  if (modelContext) {
    const contextMessage = new HumanMessage(
      `Derived economic observations (PIT-verified runtime context):\n${JSON.stringify(
        modelContext.context,
      )}`,
    );
    messages.push(contextMessage);
    replayMessages.push(contextMessage);
  }
  const effectiveModelInputHash = sha256Canonical({
    schema_version: "effective_model_input_v1",
    system_message: opts.systemMessage,
    initial_messages: opts.initialMessages.map((message) => ({
      type: message.getType(),
      content: extractTextContent(message.content as unknown),
    })),
    initial_tool_results: initialToolResults,
    model_context_hash: modelContext?.context_hash ?? null,
  });

  for (let step = 0; step < maxLoops; step++) {
    opts.onLog?.(`analysis_llm=${step + 1}/${maxLoops}`);
    const llmStartedAt = Date.now();
    const ai = (await llmWithTools.invoke(
      [new SystemMessage(opts.systemMessage), ...replayMessages],
      opts.signal ? { signal: opts.signal } : undefined,
    )) as AIMessage;
    llmElapsedMs += Date.now() - llmStartedAt;
    const usage = extractLlmTokenUsage(ai);
    promptTokens += usage.promptTokens;
    completionTokens += usage.completionTokens;
    llmInvocations++;
    messages.push(ai);

    const calls = ai.tool_calls ?? [];
    if (calls.length === 0) {
      // No more tool calls — extract the analysis text and return.
      const raw = extractTextContent(ai.content as unknown);
      let analysis = stripProcessOnlyReportPrefix(raw);
      // If the cleaned text is itself process-only narration, treat as empty
      // — caller (structured extractor) will handle the missing body.
      if (analysis && isProcessOnlyReportText(analysis)) {
        analysis = "";
      }
      return {
        analysisText: analysis,
        llmInvocations,
        toolCalls,
        toolCacheHits,
        toolExecutions,
        promptTokens,
        completionTokens,
        llmElapsedMs,
        messages,
        toolStatuses,
        modelContext,
        effectiveModelInputHash,
      };
    }

    const prunedReplay = pruneConsumedToolHistoryWithEntries(
      replayMessages,
      toolReplayEntries,
      replayFullToolMaxChars,
    );
    replayMessages = prunedReplay.messages;
    toolReplayEntries = prunedReplay.entries;
    replayMessages.push(ai);
    opts.onLog?.(
      `tools=${calls.length} names=${calls
        .map((call) => call.name ?? "unknown")
        .join(",")} fingerprints=${calls
        .map((call) => toolCallFingerprint(call.name, call.args ?? {}))
        .join(",")}`,
    );
    for (const call of calls) {
      const name = call.name ?? "";
      const fingerprint = toolCallFingerprint(call.name, call.args ?? {});
      toolCalls++;
      const tool = toolByName.get(name);
      if (!tool) {
        opts.onLog?.(`unknown tool '${name}', stubbing reply`);
        const cached = missingToolResult(name, call.args ?? {});
        toolStatuses.push(
          buildToolStatus({
            name,
            callId: call.id ?? `tool_call_${toolCalls}`,
            ...(opts.agentInvocationId ? { agentInvocationId: opts.agentInvocationId } : {}),
            args: call.args,
            shortFingerprint: fingerprint,
            cached,
            cacheHit: false,
            missing: true,
          }),
        );
        const toolMessage = new ToolMessage({
          content: cached.output,
          tool_call_id: call.id ?? "",
        });
        messages.push(toolMessage);
        replayMessages.push(toolMessage);
        continue;
      }
      let output: string;
      const cachedOutput = toolOutputCache.get(fingerprint);
      if (cachedOutput !== undefined) {
        output = cachedOutput.output;
        toolCacheHits++;
        opts.onLog?.(`tool_cache_hit fingerprint=${fingerprint}`);
        toolStatuses.push(
          buildToolStatus({
            name,
            callId: call.id ?? `tool_call_${toolCalls}`,
            ...(opts.agentInvocationId ? { agentInvocationId: opts.agentInvocationId } : {}),
            args: call.args,
            shortFingerprint: fingerprint,
            cached: cachedOutput,
            cacheHit: true,
          }),
        );
      } else {
        toolExecutions++;
        try {
          const raw = await tool.invoke(
            call.args ?? {},
            opts.signal ? { signal: opts.signal } : undefined,
          );
          output = typeof raw === "string" ? raw : String(raw);
          const metadata = toolOutputStatusMetadata(output);
          const cached = cachedToolResult({
            name,
            args: call.args ?? {},
            output,
            failed: false,
            fallback: metadata.fallback,
            ...(metadata.as_of ? { asOf: metadata.as_of } : {}),
          });
          toolOutputCache.set(fingerprint, cached);
          toolStatuses.push(
            buildToolStatus({
              name,
              callId: call.id ?? `tool_call_${toolCalls}`,
              ...(opts.agentInvocationId ? { agentInvocationId: opts.agentInvocationId } : {}),
              args: call.args,
              shortFingerprint: fingerprint,
              cached,
              cacheHit: false,
            }),
          );
        } catch (err) {
          output = `Tool '${name}' raised: ${(err as Error).message}`;
          opts.onLog?.(output);
          const cached = cachedToolResult({
            name,
            args: call.args ?? {},
            output,
            failed: true,
          });
          toolOutputCache.set(fingerprint, cached);
          toolStatuses.push(
            buildToolStatus({
              name,
              callId: call.id ?? `tool_call_${toolCalls}`,
              ...(opts.agentInvocationId ? { agentInvocationId: opts.agentInvocationId } : {}),
              args: call.args,
              shortFingerprint: fingerprint,
              cached,
              cacheHit: false,
            }),
          );
        }
      }
      const compacted = compactToolOutput(output, toolOutputMaxChars);
      if (compacted.truncated) {
        opts.onLog?.(
          `tool_output_truncated name=${name} original_chars=${compacted.originalChars} kept_chars=${compacted.text.length}`,
        );
      }
      const toolMessage = new ToolMessage({
        content: compacted.text,
        tool_call_id: call.id ?? "",
      });
      messages.push(toolMessage);
      replayMessages.push(toolMessage);
    }
  }

  // maxLoops hit — force one final non-tool invocation so we get something
  // usable. This matches the CLI tool-loop's forced-final behaviour.
  const finalStartedAt = Date.now();
  const final = (await opts.llm.invoke(
    [
      new SystemMessage(opts.systemMessage),
      ...replayMessages,
      new HumanMessage(
        "Tool budget exhausted. Now write the final structured-friendly analysis " +
          "based on the data you already have, and do not call further tools.",
      ),
    ],
    opts.signal ? { signal: opts.signal } : undefined,
  )) as AIMessage;
  llmElapsedMs += Date.now() - finalStartedAt;
  const finalUsage = extractLlmTokenUsage(final);
  promptTokens += finalUsage.promptTokens;
  completionTokens += finalUsage.completionTokens;
  llmInvocations++;
  messages.push(final);
  const raw = extractTextContent(final.content as unknown);
  const analysis = stripProcessOnlyReportPrefix(raw);
  return {
    analysisText: analysis,
    llmInvocations,
    toolCalls,
    toolCacheHits,
    toolExecutions,
    promptTokens,
    completionTokens,
    llmElapsedMs,
    messages,
    toolStatuses,
    modelContext,
    effectiveModelInputHash,
  };
}

function frozenInitialToolResult(
  call: { id: string; name: string; args: Record<string, unknown> },
  status: ToolStatus,
  output: string,
): PrivateKnotFrozenInitialToolResult {
  if (
    !status.agent_invocation_id ||
    !status.args_fingerprint ||
    !status.result_fingerprint ||
    !status.source_fingerprint
  ) {
    throw new Error("private_knot_initial_tool_result_lineage_missing");
  }
  let payload: unknown = output;
  try {
    payload = JSON.parse(output);
  } catch {
    // Preserve the exact non-JSON result as a frozen string payload.
  }
  return {
    tool_name: call.name,
    tool_call_id: call.id,
    agent_invocation_id: status.agent_invocation_id,
    args: structuredClone(call.args),
    payload,
    args_fingerprint: status.args_fingerprint,
    result_fingerprint: status.result_fingerprint,
    source_fingerprint: status.source_fingerprint,
    as_of: status.as_of ?? "unavailable",
    status: status.missing
      ? "MISSING"
      : status.failed
        ? "TOOL_FAILED"
        : status.fallback
          ? "FALLBACK"
          : "CURRENT",
  };
}
