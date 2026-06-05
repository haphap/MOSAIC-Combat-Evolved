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
  type AIMessage,
  type BaseMessage,
  HumanMessage,
  SystemMessage,
  ToolMessage,
} from "@langchain/core/messages";
import type { StructuredToolInterface } from "@langchain/core/tools";
import { extractTextContent } from "./content.js";
import { isProcessOnlyReportText, stripProcessOnlyReportPrefix } from "./process_narration.js";

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
  /** The full message thread including ToolMessages, useful for debugging. */
  messages: BaseMessage[];
}

const DEFAULT_MAX_LOOPS = 6;

export async function runAgentToolLoop(opts: AgentToolLoopOptions): Promise<AgentToolLoopResult> {
  const maxLoops = opts.maxLoops ?? DEFAULT_MAX_LOOPS;
  const toolByName = new Map(opts.tools.map((t) => [t.name, t] as const));
  const messages: BaseMessage[] = [...opts.initialMessages];
  let llmInvocations = 0;
  let toolCalls = 0;

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
    const ai = (await llmWithTools.invoke(
      [new SystemMessage(opts.systemMessage), ...messages],
      opts.signal ? { signal: opts.signal } : undefined,
    )) as AIMessage;
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
      return { analysisText: analysis, llmInvocations, toolCalls, messages };
    }

    opts.onLog?.(
      `tools=${calls.length} names=${calls
        .map((call) => call.name ?? "unknown")
        .slice(0, 5)
        .join(",")}`,
    );
    for (const call of calls) {
      const name = call.name ?? "";
      toolCalls++;
      const tool = toolByName.get(name);
      if (!tool) {
        opts.onLog?.(`unknown tool '${name}', stubbing reply`);
        messages.push(
          new ToolMessage({
            content: `Tool '${name}' is not registered for this agent.`,
            tool_call_id: call.id ?? "",
          }),
        );
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
      messages.push(
        new ToolMessage({
          content: output,
          tool_call_id: call.id ?? "",
        }),
      );
    }
  }

  // maxLoops hit — force one final non-tool invocation so we get something
  // usable. This matches Phase 1's tool-loop forced-final behaviour.
  const final = (await opts.llm.invoke(
    [
      new SystemMessage(opts.systemMessage),
      ...messages,
      new HumanMessage(
        "Tool budget exhausted. Now write the final structured-friendly analysis " +
          "based on the data you already have, and do not call further tools.",
      ),
    ],
    opts.signal ? { signal: opts.signal } : undefined,
  )) as AIMessage;
  llmInvocations++;
  messages.push(final);
  const raw = extractTextContent(final.content as unknown);
  const analysis = stripProcessOnlyReportPrefix(raw);
  return { analysisText: analysis, llmInvocations, toolCalls, messages };
}
