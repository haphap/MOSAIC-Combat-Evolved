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

import { createHash } from "node:crypto";
import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import {
  AIMessage,
  type BaseMessage,
  HumanMessage,
  SystemMessage,
  ToolMessage,
} from "@langchain/core/messages";
import type { StructuredToolInterface } from "@langchain/core/tools";
import { extractTextContent } from "./content.js";
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
  /** Forward LLM stderr / debug logs through this channel (default: silent). */
  onLog?: (msg: string) => void;
  /** Abort signal for the current agent wall-clock timeout. */
  signal?: AbortSignal;
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
  /** Observed provider prompt tokens for analysis-loop calls. */
  promptTokens: number;
  /** Observed provider completion tokens for analysis-loop calls. */
  completionTokens: number;
  /** Wall time spent awaiting analysis-loop LLM calls. */
  llmElapsedMs: number;
  /** The full message thread including ToolMessages, useful for debugging. */
  messages: BaseMessage[];
}

const DEFAULT_MAX_LOOPS = 6;
const DEFAULT_TOOL_OUTPUT_MAX_CHARS = 0;
const PRIOR_TOOL_REPLAY_CHARS = 800;

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

export function toolCallFingerprint(name: string | undefined, args: unknown): string {
  const toolName = name || "unknown";
  const hash = createHash("sha256")
    .update(JSON.stringify(canonicalize(args ?? {})))
    .digest("hex")
    .slice(0, 10);
  return `${toolName}#${hash}`;
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

export function pruneConsumedToolHistory(messages: ReadonlyArray<BaseMessage>): BaseMessage[] {
  const pruned: BaseMessage[] = [];
  let droppingToolReplies = false;
  let pendingToolCalls = new Map<string, string>();
  let retainedToolReplies: string[] = [];
  for (const message of messages) {
    if (droppingToolReplies && message.getType() !== "tool") {
      if (retainedToolReplies.length > 0) {
        pruned.push(
          new HumanMessage(`Prior tool results retained:\n${retainedToolReplies.join("\n")}`),
        );
        retainedToolReplies = [];
      }
      droppingToolReplies = false;
      pendingToolCalls = new Map();
    }
    if (hasToolCalls(message)) {
      const content = extractTextContent(message.content as unknown).trim();
      if (content) {
        pruned.push(new AIMessage(content));
      }
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
      const fingerprint = pendingToolCalls.get(toolMessage.tool_call_id) ?? "unknown#unknown";
      const output = extractTextContent(toolMessage.content as unknown);
      retainedToolReplies.push(
        `- ${fingerprint}: ${compactPriorToolReplayText(output).replaceAll("\n", "\n  ")}`,
      );
      continue;
    }
    pruned.push(message);
  }
  if (retainedToolReplies.length > 0) {
    pruned.push(
      new HumanMessage(`Prior tool results retained:\n${retainedToolReplies.join("\n")}`),
    );
  }
  return pruned;
}

export async function runAgentToolLoop(opts: AgentToolLoopOptions): Promise<AgentToolLoopResult> {
  const maxLoops = opts.maxLoops ?? DEFAULT_MAX_LOOPS;
  const toolOutputMaxChars = resolveToolOutputMaxChars();
  const toolByName = new Map(opts.tools.map((t) => [t.name, t] as const));
  const messages: BaseMessage[] = [...opts.initialMessages];
  let replayMessages: BaseMessage[] = [...opts.initialMessages];
  let llmInvocations = 0;
  let toolCalls = 0;
  let promptTokens = 0;
  let completionTokens = 0;
  let llmElapsedMs = 0;

  // Some BaseChatModel subclasses lack bindTools; the caller is responsible
  // for picking a provider that supports tool-calling. Fail loud rather than
  // silently dropping the tools.
  if (!opts.llm.bindTools) {
    throw new Error(
      "runAgentToolLoop: provider chat model does not implement bindTools — " +
        "switch to a provider/model that supports tool calling (anthropic, openai, ...).",
    );
  }
  const llmWithTools = opts.llm.bindTools(opts.tools as StructuredToolInterface[]);

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
        promptTokens,
        completionTokens,
        llmElapsedMs,
        messages,
      };
    }

    replayMessages = pruneConsumedToolHistory(replayMessages);
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
      toolCalls++;
      const tool = toolByName.get(name);
      if (!tool) {
        opts.onLog?.(`unknown tool '${name}', stubbing reply`);
        const toolMessage = new ToolMessage({
          content: `Tool '${name}' is not registered for this agent.`,
          tool_call_id: call.id ?? "",
        });
        messages.push(toolMessage);
        replayMessages.push(toolMessage);
        continue;
      }
      let output: string;
      try {
        const raw = await tool.invoke(
          call.args ?? {},
          opts.signal ? { signal: opts.signal } : undefined,
        );
        output = typeof raw === "string" ? raw : String(raw);
      } catch (err) {
        output = `Tool '${name}' raised: ${(err as Error).message}`;
        opts.onLog?.(output);
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
  // usable. This matches Phase 1's tool-loop forced-final behaviour.
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
    promptTokens,
    completionTokens,
    llmElapsedMs,
    messages,
  };
}
