/**
 * Faithful port of ``etfagents.tool_report_utils.run_tool_report_chain``.
 *
 * Each call to ``runToolReportChain`` performs a single bind-tools invocation;
 * if no tool calls are emitted, it falls through a recovery + retry sequence:
 *
 *   1. extract report text (after stripping process-narration prefixes)
 *   2. if "unexecuted tool intent" is detected, pre-run the analyst's tools and
 *      replay the prompt (no tool binding) with the results injected
 *   3. accept on the first attempt that passes ``acceptanceCheck``; otherwise
 *   4. retry with a "your previous reply was empty / process-only" fallback prompt
 *   5. retry once more with a HumanMessage nudge
 *   6. honour ``rejectedReportFallback === "last_attempt"`` to surface the best
 *      non-empty draft when every attempt fails the acceptance check.
 *
 * The tool execution loop itself lives in the LangGraph (ToolNode → analyst);
 * runToolReportChain returns ``{report: ""}`` whenever the response carries
 * tool_calls, so the graph can route to the ToolNode and re-enter the analyst
 * with the tool results appended.
 */

import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import {
  type AIMessage,
  type BaseMessage,
  HumanMessage,
  SystemMessage,
} from "@langchain/core/messages";
import type { StructuredToolInterface } from "@langchain/core/tools";
import { containsCjk, extractTextContent } from "./content.js";
import {
  isProcessOnlyReportText,
  isToolCallText,
  looksLikeUnexecutedToolIntent,
  stripProcessOnlyReportPrefix,
} from "./process_narration.js";
import { getNoProcessNarrationInstruction } from "./prompt_snippets.js";

export interface UnexecutedToolRecovery {
  /**
   * Tool names whose mention in a non-tool-call report should trigger
   * pre-execution and prompt replay. Defaults to every tool's name when the
   * caller passes the standard `tools` array.
   */
  triggerToolNames: ReadonlyArray<string>;
  /**
   * Pre-baked tool invocations to run when intent is detected. Each entry
   * pairs a tool with the payload the analyst would have used.
   */
  toolPayloads: ReadonlyArray<{
    tool: StructuredToolInterface;
    payload: Record<string, unknown>;
  }>;
}

export type SystemMessagePhase =
  /** Main pass: tools bound, full system prompt. */
  | { kind: "main" }
  /** Recovery pass: tools NOT bound, instruct model to use injected tool results. */
  | { kind: "recovery"; recoveryContext: string }
  /** Empty-response fallback: tools NOT bound, append final-report nudge. */
  | { kind: "fallback" };

/**
 * The caller owns prompt assembly. Phases:
 *   - main:      original system message verbatim
 *   - recovery:  add "you have already gathered the required tool data" suffix
 *   - fallback:  append the localized "your previous reply was empty" text
 */
export type BuildSystemMessage = (phase: SystemMessagePhase) => string;

export interface RunToolReportChainOptions {
  llm: BaseChatModel;
  tools: ReadonlyArray<StructuredToolInterface>;
  /** Conversation history excluding the system message. */
  baseMessages: ReadonlyArray<BaseMessage>;
  buildSystemMessage: BuildSystemMessage;
  /** Optional acceptance gate; report text only "passes" when this returns true. */
  acceptanceCheck?: (report: string) => boolean;
  /** Triggers + payloads for the unexecuted-tool-intent recovery path. */
  unexecutedToolRecovery?: UnexecutedToolRecovery;
  /**
   * If every attempt fails the acceptance check, return the last non-empty
   * draft (``"last_attempt"``) or an empty report (``"empty"``, default).
   */
  rejectedReportFallback?: "empty" | "last_attempt";
  /** Used to localise fallback prompts when system message is mixed-language. */
  language?: string;
}

export interface RunToolReportChainResult {
  result: AIMessage;
  /**
   * Empty when ``result.tool_calls`` is non-empty (caller routes to ToolNode)
   * or when no attempt produced an acceptable draft and ``rejectedReportFallback``
   * is ``"empty"``.
   */
  report: string;
}

export const TOOL_RECOVERY_DATA_UNAVAILABLE_PREFIX = "[tool-recovery:data-unavailable]";

export async function runToolReportChain(
  opts: RunToolReportChainOptions,
): Promise<RunToolReportChainResult> {
  const baseSystem = opts.buildSystemMessage({ kind: "main" });
  const llmWithTools = opts.llm.bindTools
    ? opts.llm.bindTools(opts.tools as StructuredToolInterface[])
    : opts.llm;
  const result = (await llmWithTools.invoke([
    new SystemMessage(baseSystem),
    ...opts.baseMessages,
  ])) as AIMessage;

  // Tool calls bubble straight back to the graph so the ToolNode can run them.
  if ((result.tool_calls ?? []).length > 0) {
    return { result, report: "" };
  }

  const initialReport = extractReportText(result);
  let lastResult: AIMessage = result;
  let lastReport = initialReport;

  // Step 1: optional unexecuted-tool-intent recovery.
  if (initialReport && opts.unexecutedToolRecovery) {
    const recovered = await tryUnexecutedToolRecovery(opts, initialReport);
    if (recovered) {
      if (recovered.markerOnly) {
        // Every recovery tool failed — surface a clear data-unavailable marker
        // so downstream code can decide what to do (mirrors the Python policy).
        return { result, report: recovered.markerText };
      }
      lastResult = recovered.result ?? lastResult;
      lastReport = recovered.report;
      if (isAccepted(recovered.report, opts.acceptanceCheck)) {
        return { result: lastResult, report: lastReport };
      }
    }
  }
  if (initialReport && isAccepted(initialReport, opts.acceptanceCheck)) {
    return { result, report: initialReport };
  }

  // Step 2: fallback prompt with no tools, plus a "you didn't write the report" nudge.
  const fallbackSystem = opts.buildSystemMessage({ kind: "fallback" });
  const fallbackResult = (await opts.llm.invoke([
    new SystemMessage(fallbackSystem),
    ...opts.baseMessages,
  ])) as AIMessage;
  const fallbackReport = extractReportText(fallbackResult);
  if (fallbackReport) {
    lastResult = fallbackResult;
    lastReport = fallbackReport;
  }
  if (isAccepted(fallbackReport, opts.acceptanceCheck)) {
    return { result: fallbackResult, report: fallbackReport };
  }

  // Step 3: stronger nudge as a HumanMessage on top of the fallback prompt.
  const nudge = buildFinalReportUserNudge(opts.language ?? guessLanguage(baseSystem));
  const nudgedResult = (await opts.llm.invoke([
    new SystemMessage(fallbackSystem),
    ...opts.baseMessages,
    new HumanMessage(nudge),
  ])) as AIMessage;
  const nudgedReport = extractReportText(nudgedResult);
  if (nudgedReport) {
    lastResult = nudgedResult;
    lastReport = nudgedReport;
  }
  if (isAccepted(nudgedReport, opts.acceptanceCheck)) {
    return { result: nudgedResult, report: nudgedReport };
  }

  if (opts.rejectedReportFallback === "last_attempt" && lastReport) {
    return { result: lastResult, report: lastReport };
  }
  return { result, report: "" };
}

/**
 * Build the "your previous reply was empty" suffix that ``runToolReportChain``
 * appends to the system message in the fallback phase. Caller assembles
 * ``{originalSystemMessage}{buildFinalReportFallback(...)}``.
 *
 * Mirrors ``_build_final_report_fallback`` in ``tool_report_utils.py``.
 */
export function buildFinalReportFallback(language: string): string {
  if (isChinesePromptLanguage(language)) {
    return (
      " 你的上一条回复没有给出最终报告正文。" +
      "下一条回复必须只输出面向用户的最终 Markdown 正文，并立刻以开篇概述段起笔。" +
      getNoProcessNarrationInstruction() +
      " 不要以“现在我来”“接下来”“下面”“我将”“我可以开始”等过程性话术开头。"
    );
  }
  return (
    " Your previous reply did not contain the finished report body. " +
    "The next reply must be the completed end-user markdown only. " +
    "Begin immediately with the opening overview paragraph in the target language. " +
    getNoProcessNarrationInstruction() +
    " Do not begin with phrases like 'Now let me', 'I will', 'I can now', 'Next', or similar process narration."
  );
}

/** Mirrors ``_build_final_report_user_nudge``. */
export function buildFinalReportUserNudge(language: string): string {
  if (isChinesePromptLanguage(language)) {
    return (
      "只返回最终 Markdown 正文。" +
      "不要写前言、状态说明或过程解释。" +
      "第一行必须是开篇概述段，不能是过程句。"
    );
  }
  return (
    "Return only the final markdown body. " +
    "No preface, no status update, no explanation. " +
    "The first line must be the opening overview paragraph, not a process sentence."
  );
}

/**
 * Build the "you have already gathered the required tool data" suffix the
 * recovery phase appends to the system message.
 */
export function buildRecoveryInstruction(): string {
  return (
    " You have already gathered the required tool data. " +
    "Do not call tools. Produce the final report from the provided tool results."
  );
}

// -------------------------------------------------------------- internals

function extractReportText(message: AIMessage): string {
  const raw = extractTextContent((message as { content?: unknown }).content);
  const stripped = stripProcessOnlyReportPrefix(raw);
  if (!stripped) return "";
  if (isToolCallText(stripped)) return "";
  if (isProcessOnlyReportText(stripped)) return "";
  return stripped;
}

function isAccepted(
  report: string,
  acceptanceCheck: ((report: string) => boolean) | undefined,
): boolean {
  if (!report) return false;
  return acceptanceCheck === undefined ? true : acceptanceCheck(report);
}

function isChinesePromptLanguage(language: string | undefined): boolean {
  if (!language) return false;
  return containsCjk(language) || /^(zh|chinese|中文)/i.test(language.trim());
}

function guessLanguage(systemMessage: string): string {
  return containsCjk(systemMessage) ? "Chinese" : "English";
}

interface RecoveryAttempt {
  result: AIMessage | null;
  report: string;
  markerOnly: boolean;
  markerText: string;
}

async function tryUnexecutedToolRecovery(
  opts: RunToolReportChainOptions,
  report: string,
): Promise<RecoveryAttempt | null> {
  const recovery = opts.unexecutedToolRecovery;
  if (!recovery) return null;

  const matched = new Set(
    recovery.triggerToolNames.filter((name) => looksLikeUnexecutedToolIntent(report, name)),
  );
  if (matched.size === 0) return null;

  const targetedPayloads = recovery.toolPayloads.filter((entry) => matched.has(entry.tool.name));
  const payloadsToRun = targetedPayloads.length > 0 ? targetedPayloads : recovery.toolPayloads;
  if (payloadsToRun.length === 0) return null;

  const sections: string[] = [];
  let toolFailures = 0;
  for (const { tool, payload } of payloadsToRun) {
    try {
      const output = await tool.invoke(payload);
      sections.push(`### ${tool.name} result\n${String(output)}`);
    } catch (err) {
      toolFailures += 1;
      sections.push(`### ${tool.name} result\n${tool.name} failed: ${(err as Error).message}`);
    }
  }

  if (toolFailures === sections.length) {
    return {
      result: null,
      report: "",
      markerOnly: true,
      markerText:
        `${TOOL_RECOVERY_DATA_UNAVAILABLE_PREFIX}\n` +
        "Required data tools were unavailable, so the final report cannot be completed " +
        `without risking unsupported analysis.\n\n${sections.join("\n\n")}`,
    };
  }

  const recoveryContext =
    "The previous assistant response described a future tool call but did not execute it. " +
    "The required tools have now been executed below. Write the complete final markdown report now. " +
    "Do not mention that a recovery happened, do not explain your process, and do not call tools.\n\n" +
    sections.join("\n\n");

  const recoverySystem = opts.buildSystemMessage({ kind: "recovery", recoveryContext });
  const recoveredResult = (await opts.llm.invoke([
    new SystemMessage(recoverySystem),
    ...opts.baseMessages,
    new HumanMessage(recoveryContext),
  ])) as AIMessage;
  const recoveredReport = extractReportText(recoveredResult);

  return {
    result: recoveredResult,
    report: recoveredReport,
    markerOnly: false,
    markerText: "",
  };
}
