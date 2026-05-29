/**
 * Phase 1 Exit: drive a minimal tool-calling loop with one bridge tool.
 *
 * Flow:
 *   1. Resolve config from the bridge.
 *   2. Build a chat model from that config + env API key (Anthropic by default
 *      per Plan §1; switch via `--provider lemonade` for zero-cost local dev).
 *   3. Wrap one bridge tool (default: get_fred_series) as a LangChain tool.
 *   4. Loop: invoke LLM → if tool_calls, dispatch → feed back → repeat.
 *   5. Print the final assistant message.
 */

import type { BaseMessage } from "@langchain/core/messages";
import { type AIMessage, HumanMessage, SystemMessage, ToolMessage } from "@langchain/core/messages";
import type { StructuredToolInterface } from "@langchain/core/tools";
import type { Command } from "commander";
import pc from "picocolors";
import { BridgeApi, BridgeClient, pickBridgeTools, RpcError } from "../../bridge/index.js";
import { createLlmFromConfig } from "../../llm/factory.js";

const DEFAULT_TOOL = "get_fred_series";
const DEFAULT_QUESTION =
  "请用中文简要描述美国 FEDFUNDS 利率在 2024 年上半年的走势。" +
  "调用 get_fred_series 工具拉取 2024-01-01 至 2024-06-30 的 FEDFUNDS 序列后再作答，" +
  "答复中点出关键的政策转折点。";
const MAX_LOOPS = 6;

interface LoopOptions {
  tool?: string;
  model?: string;
  provider?: string;
  question?: string;
  asOfDate?: string;
}

export function registerToolLoop(program: Command): void {
  program
    .command("tool-loop")
    .description(
      "Phase 1 Exit demo: one chat model + one bridge tool. " +
        "Default tool is get_fred_series (requires FRED_API_KEY).",
    )
    .option("--tool <name>", `Bridge tool to expose to the LLM (default: ${DEFAULT_TOOL})`)
    .option("--model <name>", "Override LLM model from bridge config")
    .option("--provider <name>", "Override LLM provider from bridge config")
    .option("--question <text>", "Override the user question")
    .option("--as-of-date <date>", "Run tool calls in backtest mode pinned to YYYY-MM-DD")
    .action(async (opts: LoopOptions) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        await client.start();
        const config = await api.configGet();
        const llmHandle = createLlmFromConfig(config, {
          tier: "quick",
          ...(opts.model ? { model: opts.model } : {}),
          ...(opts.provider ? { provider: opts.provider } : {}),
        });
        const toolName = opts.tool ?? DEFAULT_TOOL;
        const [boundTool] = await pickBridgeTools(api, [toolName], {
          ...(opts.asOfDate ? { context: { mode: "backtest", as_of_date: opts.asOfDate } } : {}),
        });
        if (!boundTool) {
          throw new Error(`Bridge tool ${toolName} not available`);
        }
        const llmWithTools = llmHandle.llm.bindTools?.([boundTool]);
        if (!llmWithTools) {
          throw new Error(
            `Provider '${llmHandle.provider}' chat model does not implement bindTools — ` +
              `cannot run a tool-calling loop. Pick a provider/model that supports tools.`,
          );
        }

        console.log(
          pc.dim(
            `provider=${llmHandle.provider} model=${llmHandle.model} tool=${toolName}` +
              (opts.asOfDate ? ` as_of_date=${opts.asOfDate}` : ""),
          ),
        );

        const question = opts.question ?? DEFAULT_QUESTION;
        const messages: BaseMessage[] = [
          new SystemMessage(
            "你是 MOSAIC 宏观研究助手。当用户提出关于宏观经济、市场或政策的问题时，" +
              "先调用提供的工具拉取数据，再基于工具返回的内容用中文作答；" +
              "回答应简洁、客观，不编造工具未返回的信息。",
          ),
          new HumanMessage(question),
        ];

        const final = await runToolLoop(messages, llmWithTools, llmHandle.llm, [boundTool]);
        const text = extractText(final);
        console.log(pc.cyan("\n=== assistant ==="));
        console.log(text || pc.dim("(empty)"));
      } catch (err) {
        if (err instanceof RpcError) {
          console.error(pc.red(`bridge error [${err.code}]: ${err.message}`));
        } else {
          console.error(pc.red(`error: ${(err as Error).message}`));
        }
        const tail = client.stderrTail.trim();
        if (tail) {
          console.error(pc.dim("\n--- bridge stderr (tail) ---"));
          console.error(pc.dim(tail.slice(-2000)));
        }
        process.exitCode = 1;
      } finally {
        await client.close();
      }
    });
}

interface BoundLlm {
  invoke(messages: BaseMessage[]): Promise<AIMessage>;
}

/** Exported for unit testing — the CLI flow above is the only runtime caller. */
export async function runToolLoop(
  messages: BaseMessage[],
  llm: BoundLlm,
  unboundLlm: BoundLlm,
  tools: StructuredToolInterface[],
  maxLoops: number = MAX_LOOPS,
): Promise<AIMessage> {
  const toolByName = new Map(tools.map((t) => [t.name, t] as const));

  for (let step = 0; step < maxLoops; step++) {
    const ai = await llm.invoke(messages);
    messages.push(ai);

    const toolCalls = ai.tool_calls ?? [];
    if (toolCalls.length === 0) {
      return ai;
    }

    for (const call of toolCalls) {
      const tool = call.name ? toolByName.get(call.name) : undefined;
      if (!tool) {
        messages.push(
          new ToolMessage({
            content: `Tool '${call.name}' is not available.`,
            tool_call_id: call.id ?? "",
          }),
        );
        continue;
      }
      let content: string;
      try {
        content = await tool.invoke(call.args ?? {});
      } catch (err) {
        content = `Tool '${call.name}' raised: ${(err as Error).message}`;
      }
      console.log(pc.dim(`[tool ${call.name}] ${truncate(content, 200)}`));
      messages.push(
        new ToolMessage({
          content,
          tool_call_id: call.id ?? "",
        }),
      );
    }
  }
  // Forced exit: ask the **unbound** LLM (no tools) for a final answer.
  // Using the tool-bound model here would let it keep emitting tool_calls
  // and ignore the "do not call tools" instruction in the prompt — the
  // tool privilege has to be revoked at the model layer, not at the
  // prompt layer.
  const final = await unboundLlm.invoke([
    ...messages,
    new HumanMessage("工具调用次数已达到上限。请基于已有信息直接给出最终回答，不再调用工具。"),
  ]);
  return final;
}

function extractText(message: AIMessage): string {
  const content = message.content;
  if (typeof content === "string") {
    return content;
  }
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        if (typeof part === "string") return part;
        if (part && typeof part === "object" && "text" in part) {
          return String((part as { text: unknown }).text ?? "");
        }
        return "";
      })
      .join("");
  }
  return String(content);
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max)}…`;
}
